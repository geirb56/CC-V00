from fastapi import APIRouter, HTTPException, Depends, Query, Request
from fastapi.responses import RedirectResponse
from typing import Optional, List
import logging
import os
import secrets
import hashlib
import base64
import httpx
import uuid
from datetime import datetime, timezone, timedelta

from database import db
from models import GarminConnectionStatus, GarminSyncResult, StravaConnectionStatus, StravaSyncResult, WebhookSubscriptionRequest, WebhookSubscriptionResponse
from api.deps import auth_user

router = APIRouter()
logger = logging.getLogger(__name__)

GARMIN_CLIENT_ID = os.environ.get('GARMIN_CLIENT_ID', '')
GARMIN_CLIENT_SECRET = os.environ.get('GARMIN_CLIENT_SECRET', '')
GARMIN_REDIRECT_URI = os.environ.get('GARMIN_REDIRECT_URI', '')
STRAVA_CLIENT_ID = os.environ.get('STRAVA_CLIENT_ID', '')
STRAVA_CLIENT_SECRET = os.environ.get('STRAVA_CLIENT_SECRET', '')
STRAVA_REDIRECT_URI = os.environ.get('STRAVA_REDIRECT_URI', '')
FRONTEND_URL = os.environ.get('FRONTEND_URL', 'http://localhost:3000')
STRAVA_WEBHOOK_VERIFY_TOKEN = os.environ.get("STRAVA_WEBHOOK_VERIFY_TOKEN", "cardiocoach_webhook_secret_2024")


def generate_pkce_pair() -> tuple:
    """Generate PKCE code verifier and code challenge"""
    code_verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode('utf-8').rstrip('=')
    code_challenge = base64.urlsafe_b64encode(
        hashlib.sha256(code_verifier.encode('utf-8')).digest()
    ).decode('utf-8').rstrip('=')
    return code_verifier, code_challenge


def get_garmin_auth_url(code_challenge: str, state: str) -> str:
    """Generate Garmin Connect authorization URL"""
    params = {
        "client_id": GARMIN_CLIENT_ID,
        "response_type": "code",
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "redirect_uri": GARMIN_REDIRECT_URI,
        "state": state,
        "scope": "activity_export"
    }
    query = "&".join(f"{k}={v}" for k, v in params.items())
    return f"https://connect.garmin.com/oauthConfirm?{query}"


async def exchange_garmin_code(code: str, code_verifier: str) -> dict:
    """Exchange authorization code for access token"""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "https://connectapi.garmin.com/oauth-service/oauth/token",
            data={
                "grant_type": "authorization_code",
                "client_id": GARMIN_CLIENT_ID,
                "client_secret": GARMIN_CLIENT_SECRET,
                "code": code,
                "code_verifier": code_verifier,
                "redirect_uri": GARMIN_REDIRECT_URI
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"}
        )
        response.raise_for_status()
        return response.json()


async def fetch_garmin_activities(access_token: str, start_date: str = None) -> list:
    """Fetch activities from Garmin Connect API"""
    async with httpx.AsyncClient() as client:
        params = {"limit": 100}
        if start_date:
            params["start"] = start_date
        
        response = await client.get(
            "https://apis.garmin.com/wellness-api/rest/activities",
            headers={"Authorization": f"Bearer {access_token}"},
            params=params
        )
        response.raise_for_status()
        return response.json()


def convert_garmin_to_workout(garmin_activity: dict, user_id: str = "default") -> dict:
    """Convert Garmin activity to CardioCoach workout format"""
    # Map Garmin activity types to our types
    activity_type_map = {
        "running": "run",
        "cycling": "cycle",
        "indoor_cycling": "cycle",
        "trail_running": "run",
        "treadmill_running": "run",
        "virtual_ride": "cycle",
        "road_biking": "cycle",
        "mountain_biking": "cycle",
    }
    
    garmin_type = garmin_activity.get("activityType", "").lower()
    workout_type = activity_type_map.get(garmin_type, None)
    
    # Only import running and cycling
    if not workout_type:
        return None
    
    # Extract metrics with graceful fallback for missing data
    duration_seconds = garmin_activity.get("duration", 0)
    distance_meters = garmin_activity.get("distance", 0)
    avg_hr = garmin_activity.get("averageHR")
    max_hr = garmin_activity.get("maxHR")
    calories = garmin_activity.get("calories")
    elevation = garmin_activity.get("elevationGain")
    
    # Calculate pace/speed
    avg_pace = None
    avg_speed = None
    if distance_meters and duration_seconds:
        if workout_type == "run":
            # Pace in min/km
            avg_pace = (duration_seconds / 60) / (distance_meters / 1000) if distance_meters > 0 else None
        else:
            # Speed in km/h
            avg_speed = (distance_meters / 1000) / (duration_seconds / 3600) if duration_seconds > 0 else None
    
    # Extract heart rate zones if available
    hr_zones = garmin_activity.get("heartRateZones")
    effort_distribution = None
    if hr_zones and isinstance(hr_zones, list) and len(hr_zones) >= 5:
        total_time = sum(z.get("secsInZone", 0) for z in hr_zones[:5])
        if total_time > 0:
            effort_distribution = {
                f"z{i+1}": round((hr_zones[i].get("secsInZone", 0) / total_time) * 100)
                for i in range(5)
            }
    
    # Build workout object
    start_time = garmin_activity.get("startTimeLocal") or garmin_activity.get("startTimeGMT")
    if start_time:
        try:
            if isinstance(start_time, (int, float)):
                date_obj = datetime.fromtimestamp(start_time / 1000, tz=timezone.utc)
            else:
                date_obj = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
            date_str = date_obj.strftime("%Y-%m-%d")
        except (ValueError, TypeError, AttributeError):
            date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    else:
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Build workout object
    workout = {
        "id": f"garmin_{garmin_activity.get('activityId', uuid.uuid4())}",
        "type": workout_type,
        "name": garmin_activity.get("activityName", f"{workout_type.title()} Workout"),
        "date": date_str,
        "duration_minutes": round(duration_seconds / 60) if duration_seconds else 0,
        "distance_km": round(distance_meters / 1000, 2) if distance_meters else 0,
        "data_source": "garmin",
        "garmin_activity_id": str(garmin_activity.get("activityId")),
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    
    # Add optional fields only if present (graceful handling)
    if avg_hr:
        workout["avg_heart_rate"] = int(avg_hr)
    if max_hr:
        workout["max_heart_rate"] = int(max_hr)
    if avg_pace:
        workout["avg_pace_min_km"] = round(avg_pace, 2)
    if avg_speed:
        workout["avg_speed_kmh"] = round(avg_speed, 1)
    if calories:
        workout["calories"] = int(calories)
    if elevation:
        workout["elevation_gain_m"] = int(elevation)
    if effort_distribution:
        workout["effort_zone_distribution"] = effort_distribution
    
    return workout


async def exchange_strava_code(code: str) -> dict:
    """Exchange authorization code for Strava access token"""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "https://www.strava.com/api/v3/oauth/token",
            data={
                "client_id": STRAVA_CLIENT_ID,
                "client_secret": STRAVA_CLIENT_SECRET,
                "code": code,
                "grant_type": "authorization_code"
            }
        )
        response.raise_for_status()
        return response.json()


async def refresh_strava_token(refresh_token: str) -> dict:
    """Refresh Strava access token"""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "https://www.strava.com/api/v3/oauth/token",
            data={
                "client_id": STRAVA_CLIENT_ID,
                "client_secret": STRAVA_CLIENT_SECRET,
                "grant_type": "refresh_token",
                "refresh_token": refresh_token
            }
        )
        response.raise_for_status()
        return response.json()


async def fetch_strava_activities(access_token: str, per_page: int = 100, max_pages: int = 3) -> list:
    """Fetch activities from Strava API (up to max_pages * per_page activities)"""
    all_activities = []
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        for page in range(1, max_pages + 1):
            response = await client.get(
                "https://www.strava.com/api/v3/athlete/activities",
                headers={"Authorization": f"Bearer {access_token}"},
                params={"per_page": per_page, "page": page}
            )
            response.raise_for_status()
            activities = response.json()
            
            if not activities:
                break  # No more activities
            
            all_activities.extend(activities)
            
            if len(activities) < per_page:
                break  # Last page
    
    logger.info(f"Fetched {len(all_activities)} activities from Strava")
    return all_activities


async def fetch_strava_activity_streams(access_token: str, activity_id: str) -> dict:
    """Fetch detailed streams (HR, pace, cadence) for a specific activity"""
    streams_data = {}
    
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            # Fetch HR, velocity, cadence, altitude streams
            response = await client.get(
                f"https://www.strava.com/api/v3/activities/{activity_id}/streams",
                headers={"Authorization": f"Bearer {access_token}"},
                params={
                    "keys": "heartrate,velocity_smooth,cadence,altitude,time,distance,grade_smooth",
                    "key_by_type": "true"
                }
            )
            
            if response.status_code == 200:
                streams = response.json()
                streams_data = streams
            else:
                logger.warning(f"Failed to fetch streams for activity {activity_id}: {response.status_code}")
    except Exception as e:
        logger.warning(f"Error fetching streams for activity {activity_id}: {e}")
    
    return streams_data


async def fetch_strava_activity_laps(access_token: str, activity_id: str) -> list:
    """Fetch lap data for a specific activity (splits per km)"""
    laps_data = []
    
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(
                f"https://www.strava.com/api/v3/activities/{activity_id}/laps",
                headers={"Authorization": f"Bearer {access_token}"}
            )
            
            if response.status_code == 200:
                laps_data = response.json()
            else:
                logger.warning(f"Failed to fetch laps for activity {activity_id}: {response.status_code}")
    except Exception as e:
        logger.warning(f"Error fetching laps for activity {activity_id}: {e}")
    
    return laps_data


def process_strava_laps(laps: list) -> list:
    """Convert Strava laps to anonymized split data"""
    splits = []
    for i, lap in enumerate(laps, 1):
        distance_km = lap.get("distance", 0) / 1000
        elapsed_time = lap.get("elapsed_time", 0)  # seconds
        moving_time = lap.get("moving_time", elapsed_time)
        avg_speed = lap.get("average_speed", 0)  # m/s
        avg_hr = lap.get("average_heartrate")
        max_hr = lap.get("max_heartrate")
        avg_cadence = lap.get("average_cadence")
        elevation_gain = lap.get("total_elevation_gain", 0)
        
        # Calculate pace min/km
        if avg_speed > 0:
            pace_min_km = (1000 / avg_speed) / 60
            pace_str = f"{int(pace_min_km)}:{int((pace_min_km % 1) * 60):02d}"
        else:
            pace_min_km = None
            pace_str = "N/A"
        
        splits.append({
            "lap_num": i,
            "distance_km": round(distance_km, 2),
            "elapsed_time_sec": elapsed_time,
            "moving_time_sec": moving_time,
            "pace_min_km": round(pace_min_km, 2) if pace_min_km else None,
            "pace_str": pace_str,
            "avg_hr": avg_hr,
            "max_hr": max_hr,
            "avg_cadence": int(avg_cadence * 2) if avg_cadence else None,  # Strava returns half cadence
            "elevation_gain": elevation_gain
        })
    
    return splits


def process_strava_streams(streams_data: dict, distance_km: float) -> dict:
    """Process streams into per-km detailed data"""
    detailed_data = {
        "hr_data": [],
        "cadence_data": [],
        "pace_data": [],
        "altitude_data": [],
        "km_splits": []
    }
    
    if not streams_data:
        return detailed_data
    
    # Extract raw streams
    hr_stream = streams_data.get("heartrate", {}).get("data", [])
    cadence_stream = streams_data.get("cadence", {}).get("data", [])
    velocity_stream = streams_data.get("velocity_smooth", {}).get("data", [])
    altitude_stream = streams_data.get("altitude", {}).get("data", [])
    distance_stream = streams_data.get("distance", {}).get("data", [])
    time_stream = streams_data.get("time", {}).get("data", [])
    
    # Store raw data (sampled for storage efficiency)
    sample_rate = max(1, len(hr_stream) // 200)  # Max 200 points
    detailed_data["hr_data"] = hr_stream[::sample_rate] if hr_stream else []
    detailed_data["cadence_data"] = [c * 2 if c else None for c in cadence_stream[::sample_rate]] if cadence_stream else []
    detailed_data["altitude_data"] = altitude_stream[::sample_rate] if altitude_stream else []
    
    # Convert velocity to pace (min/km)
    if velocity_stream:
        pace_data = []
        for v in velocity_stream[::sample_rate]:
            if v and v > 0:
                pace_min_km = (1000 / v) / 60
                pace_data.append(round(pace_min_km, 2))
            else:
                pace_data.append(None)
        detailed_data["pace_data"] = pace_data
    
    # Calculate per-km splits from streams
    if distance_stream and time_stream and velocity_stream:
        km_splits = []
        current_km = 1
        km_start_idx = 0
        
        for i, dist in enumerate(distance_stream):
            dist_km = dist / 1000
            if dist_km >= current_km:
                # Calculate stats for this km
                km_hr = hr_stream[km_start_idx:i] if hr_stream else []
                km_cadence = cadence_stream[km_start_idx:i] if cadence_stream else []
                km_velocity = velocity_stream[km_start_idx:i] if velocity_stream else []
                km_time = time_stream[i] - time_stream[km_start_idx] if time_stream else 0
                
                avg_hr = sum([h for h in km_hr if h]) / len([h for h in km_hr if h]) if km_hr else None
                avg_cadence = sum([c for c in km_cadence if c]) / len([c for c in km_cadence if c]) if km_cadence else None
                avg_velocity = sum([v for v in km_velocity if v]) / len([v for v in km_velocity if v]) if km_velocity else None
                
                if avg_velocity and avg_velocity > 0:
                    pace_min_km = (1000 / avg_velocity) / 60
                    pace_str = f"{int(pace_min_km)}:{int((pace_min_km % 1) * 60):02d}"
                else:
                    pace_min_km = None
                    pace_str = "N/A"
                
                km_splits.append({
                    "km": current_km,
                    "time_sec": km_time,
                    "pace_min_km": round(pace_min_km, 2) if pace_min_km else None,
                    "pace_str": pace_str,
                    "avg_hr": round(avg_hr) if avg_hr else None,
                    "avg_cadence": round(avg_cadence * 2) if avg_cadence else None,
                })
                
                current_km += 1
                km_start_idx = i
        
        detailed_data["km_splits"] = km_splits
    
    return detailed_data


async def fetch_strava_activity_zones(access_token: str, activity_id: str) -> dict:
    """Fetch heart rate zones distribution for a specific activity"""
    zones_data = {}
    
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(
                f"https://www.strava.com/api/v3/activities/{activity_id}/zones",
                headers={"Authorization": f"Bearer {access_token}"}
            )
            
            if response.status_code == 200:
                zones = response.json()
                zones_data = zones
            else:
                logger.warning(f"Failed to fetch zones for activity {activity_id}: {response.status_code}")
    except Exception as e:
        logger.warning(f"Error fetching zones for activity {activity_id}: {e}")
    
    return zones_data


def calculate_hr_zones_from_stream(hr_stream: list, max_hr: int = None) -> dict:
    """Calculate time spent in each HR zone from stream data"""
    if not hr_stream or not max_hr:
        return None
    
    # Standard 5-zone model based on % of max HR
    # Z1: 50-60%, Z2: 60-70%, Z3: 70-80%, Z4: 80-90%, Z5: 90-100%
    zone_thresholds = [
        (0.50, 0.60, "z1"),
        (0.60, 0.70, "z2"),
        (0.70, 0.80, "z3"),
        (0.80, 0.90, "z4"),
        (0.90, 1.00, "z5"),
    ]
    
    zone_counts = {"z1": 0, "z2": 0, "z3": 0, "z4": 0, "z5": 0}
    total_points = len(hr_stream)
    
    for hr in hr_stream:
        if hr is None:
            continue
        hr_pct = hr / max_hr
        
        for low, high, zone in zone_thresholds:
            if low <= hr_pct < high:
                zone_counts[zone] += 1
                break
        else:
            # Above 100% max HR
            if hr_pct >= 1.0:
                zone_counts["z5"] += 1
    
    # Convert to percentages
    if total_points > 0:
        zone_distribution = {
            zone: round((count / total_points) * 100)
            for zone, count in zone_counts.items()
        }
    else:
        zone_distribution = {"z1": 0, "z2": 0, "z3": 0, "z4": 0, "z5": 0}
    
    return zone_distribution


def calculate_pace_stats_from_stream(velocity_stream: list, time_stream: list = None) -> dict:
    """Calculate detailed pace statistics from velocity stream (for running)"""
    if not velocity_stream:
        return None
    
    # Filter out zero/null values
    valid_velocities = [v for v in velocity_stream if v and v > 0]
    
    if not valid_velocities:
        return None
    
    # Convert m/s to min/km
    def ms_to_pace(v):
        if v <= 0:
            return None
        km_per_sec = v / 1000
        if km_per_sec <= 0:
            return None
        return 1 / (km_per_sec * 60)  # min/km
    
    paces = [ms_to_pace(v) for v in valid_velocities if ms_to_pace(v)]
    
    if not paces:
        return None
    
    avg_pace = sum(paces) / len(paces)
    min_pace = min(paces)  # Fastest
    max_pace = max(paces)  # Slowest
    
    # Calculate pace variability (standard deviation)
    variance = sum((p - avg_pace) ** 2 for p in paces) / len(paces)
    std_dev = variance ** 0.5
    
    return {
        "avg_pace_min_km": round(avg_pace, 2),
        "best_pace_min_km": round(min_pace, 2),
        "slowest_pace_min_km": round(max_pace, 2),
        "pace_variability": round(std_dev, 2)
    }


def convert_strava_to_workout(strava_activity: dict, streams_data: dict = None, zones_data: dict = None) -> dict:
    """Convert Strava activity to CardioCoach workout format with detailed HR and pace data"""
    # Map Strava activity types to our types
    activity_type_map = {
        "run": "run",
        "ride": "cycle",
        "virtualrun": "run",
        "virtualride": "cycle",
        "trailrun": "run",
        "mountainbikeride": "cycle",
        "gravelride": "cycle",
        "ebikeride": "cycle",
    }
    
    strava_type = strava_activity.get("type", "").lower()
    workout_type = activity_type_map.get(strava_type, None)
    
    # Only import running and cycling
    if not workout_type:
        return None
    
    # Extract metrics with graceful fallback for missing data
    elapsed_time = strava_activity.get("elapsed_time", 0)  # in seconds
    moving_time = strava_activity.get("moving_time", elapsed_time)  # in seconds
    distance = strava_activity.get("distance", 0)  # in meters
    avg_hr = strava_activity.get("average_heartrate")
    max_hr = strava_activity.get("max_heartrate")
    elevation = strava_activity.get("total_elevation_gain")
    calories = strava_activity.get("calories")
    avg_speed = strava_activity.get("average_speed", 0)  # in m/s
    max_speed = strava_activity.get("max_speed", 0)  # in m/s
    avg_cadence = strava_activity.get("average_cadence")
    
    # Calculate pace (for runs) or speed (for rides)
    avg_pace_min_km = None
    best_pace_min_km = None
    avg_speed_kmh = None
    max_speed_kmh = None
    
    if avg_speed and avg_speed > 0:
        if workout_type == "run":
            # Convert m/s to min/km
            speed_km_per_min = (avg_speed * 60) / 1000
            if speed_km_per_min > 0:
                avg_pace_min_km = round(1 / speed_km_per_min, 2)
            # Best pace from max speed
            if max_speed and max_speed > 0:
                max_speed_km_per_min = (max_speed * 60) / 1000
                if max_speed_km_per_min > 0:
                    best_pace_min_km = round(1 / max_speed_km_per_min, 2)
        else:
            # Convert m/s to km/h
            avg_speed_kmh = round(avg_speed * 3.6, 1)
            if max_speed:
                max_speed_kmh = round(max_speed * 3.6, 1)
    
    # Parse start time
    start_date = strava_activity.get("start_date_local") or strava_activity.get("start_date")
    if start_date:
        try:
            date_obj = datetime.fromisoformat(start_date.replace("Z", "+00:00"))
            date_str = date_obj.strftime("%Y-%m-%d")
        except (ValueError, TypeError, AttributeError):
            date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    else:
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    
    # Build workout object
    workout = {
        "id": f"strava_{strava_activity.get('id', uuid.uuid4())}",
        "type": workout_type,
        "name": strava_activity.get("name", f"{workout_type.title()} Workout"),
        "date": date_str,
        "duration_minutes": round(elapsed_time / 60) if elapsed_time else 0,
        "moving_time_minutes": round(moving_time / 60) if moving_time else 0,
        "distance_km": round(distance / 1000, 2) if distance else 0,
        "data_source": "strava",
        "strava_activity_id": str(strava_activity.get("id")),
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    
    # Heart rate data
    if avg_hr:
        workout["avg_heart_rate"] = int(avg_hr)
    if max_hr:
        workout["max_heart_rate"] = int(max_hr)
    
    # Calculate HR zones - PRIORITY: Use Strava's zone data first (uses athlete's configured max HR)
    # Fallback to our calculation if Strava zones not available
    hr_zones = None
    
    # 1. First try Strava's own zone distribution (most accurate, uses athlete settings)
    if zones_data:
        for zone_info in zones_data:
            if zone_info.get("type") == "heartrate":
                distribution_buckets = zone_info.get("distribution_buckets", [])
                if distribution_buckets:
                    total_time = sum(b.get("time", 0) for b in distribution_buckets)
                    if total_time > 0:
                        hr_zones = {}
                        for i, bucket in enumerate(distribution_buckets[:5]):
                            zone_key = f"z{i+1}"
                            hr_zones[zone_key] = round((bucket.get("time", 0) / total_time) * 100)
                        logger.debug(f"Using Strava zones for {workout.get('name', 'workout')}")
    
    # 2. Fallback: Calculate from HR stream using estimated max HR (220 - age, default 185)
    if not hr_zones and streams_data and "heartrate" in streams_data:
        hr_stream = streams_data["heartrate"].get("data", [])
        if hr_stream:
            # Use athlete's theoretical max HR (not session max!)
            # Default to 185 bpm if not configured (typical for ~35 year old)
            athlete_max_hr = 185  # TODO: Get from user settings
            hr_zones = calculate_hr_zones_from_stream(hr_stream, athlete_max_hr)
            logger.debug(f"Calculated zones from stream for {workout.get('name', 'workout')}")
    
    if hr_zones:
        workout["effort_zone_distribution"] = hr_zones
    
    # Pace data (running)
    if workout_type == "run":
        if avg_pace_min_km:
            workout["avg_pace_min_km"] = avg_pace_min_km
        if best_pace_min_km:
            workout["best_pace_min_km"] = best_pace_min_km
        
        # Detailed pace stats from streams
        if streams_data and "velocity_smooth" in streams_data:
            velocity_stream = streams_data["velocity_smooth"].get("data", [])
            pace_stats = calculate_pace_stats_from_stream(velocity_stream)
            if pace_stats:
                workout["pace_stats"] = pace_stats
        
        # Cadence (steps per minute, Strava gives half - one foot)
        if avg_cadence:
            workout["avg_cadence_spm"] = int(avg_cadence * 2)  # Convert to full steps
    
    # Speed data (cycling)
    if workout_type == "cycle":
        if avg_speed_kmh:
            workout["avg_speed_kmh"] = avg_speed_kmh
        if max_speed_kmh:
            workout["max_speed_kmh"] = max_speed_kmh
        if avg_cadence:
            workout["avg_cadence_rpm"] = int(avg_cadence)
    
    # Elevation and calories
    if calories:
        workout["calories"] = int(calories)
    if elevation:
        workout["elevation_gain_m"] = int(elevation)
    
    return workout


def enrich_workout_with_detailed_data(workout: dict, streams_data: dict, laps_data: list) -> dict:
    """Enrich workout with detailed Strava data (splits, HR/cadence/pace per km)"""
    if not workout:
        return workout
    
    distance_km = workout.get("distance_km", 0)
    expected_km_count = int(distance_km) + (1 if distance_km % 1 > 0.3 else 0)  # Ex: 6.7km = 7 splits
    
    # Process streams FIRST to get accurate km_splits
    km_splits = []
    if streams_data:
        detailed = process_strava_streams(streams_data, distance_km)
        
        # Store km splits from streams (accurate per-km data)
        if detailed.get("km_splits"):
            km_splits = detailed["km_splits"]
            workout["km_splits"] = km_splits
        
        # Store sampled data for RAG retrieval
        if detailed.get("hr_data"):
            workout["hr_stream_sample"] = detailed["hr_data"][:50]  # First 50 points
            # HR analysis
            hr_data = [h for h in detailed["hr_data"] if h]
            if hr_data:
                workout["hr_analysis"] = {
                    "min_hr": min(hr_data),
                    "max_hr": max(hr_data),
                    "avg_hr": round(sum(hr_data) / len(hr_data)),
                    "hr_drift": round(sum(hr_data[-10:]) / 10 - sum(hr_data[:10]) / 10) if len(hr_data) >= 20 else 0,
                }
        
        if detailed.get("cadence_data"):
            workout["cadence_stream_sample"] = detailed["cadence_data"][:50]
            cadence_data = [c for c in detailed["cadence_data"] if c]
            if cadence_data:
                workout["cadence_analysis"] = {
                    "min_cadence": min(cadence_data),
                    "max_cadence": max(cadence_data),
                    "avg_cadence": round(sum(cadence_data) / len(cadence_data)),
                    "cadence_stability": round(100 - (max(cadence_data) - min(cadence_data)) / 2, 1),
                }
        
        if detailed.get("altitude_data"):
            alt_data = [a for a in detailed["altitude_data"] if a is not None]
            if alt_data:
                workout["elevation_analysis"] = {
                    "min_altitude": round(min(alt_data)),
                    "max_altitude": round(max(alt_data)),
                    "total_climb": round(sum(max(0, alt_data[i] - alt_data[i-1]) for i in range(1, len(alt_data)))),
                    "total_descent": round(sum(max(0, alt_data[i-1] - alt_data[i]) for i in range(1, len(alt_data)))),
                }
    
    # Use km_splits for split analysis (accurate per-km) OR fall back to laps if close to expected
    use_km_splits = len(km_splits) > 0 and abs(len(km_splits) - expected_km_count) <= 2
    
    if use_km_splits:
        # Use km_splits from streams (more accurate)
        splits = []
        for i, ks in enumerate(km_splits):
            splits.append({
                "lap_num": i + 1,
                "pace_min_km": ks.get("pace_min", 0),
                "pace_str": ks.get("pace_str", "N/A"),
                "avg_hr": ks.get("avg_hr"),
                "avg_cadence": ks.get("avg_cadence"),
            })
        workout["splits"] = splits
        
        # Analyze km splits
        paces = [s["pace_min_km"] for s in splits if s.get("pace_min_km") and s["pace_min_km"] > 0]
        if paces:
            fastest_split = min(paces)
            slowest_split = max(paces)
            
            # Find fastest and slowest km
            fastest_km = next((s["lap_num"] for s in splits if s.get("pace_min_km") == fastest_split), None)
            slowest_km = next((s["lap_num"] for s in splits if s.get("pace_min_km") == slowest_split), None)
            
            workout["split_analysis"] = {
                "fastest_split_pace": round(fastest_split, 2),
                "slowest_split_pace": round(slowest_split, 2),
                "fastest_km": fastest_km,
                "slowest_km": slowest_km,
                "pace_drop": round(slowest_split - fastest_split, 2),
                "consistency_score": round(max(0, 100 - (slowest_split - fastest_split) * 10), 1),
                "negative_split": paces[-1] < paces[0] if len(paces) >= 2 else False,
                "total_splits": len(splits)
            }
    elif laps_data and abs(len(laps_data) - expected_km_count) <= 2:
        # Fall back to laps ONLY if they match expected km count (likely auto-lap per km)
        splits = process_strava_laps(laps_data)
        workout["splits"] = splits
        
        if splits:
            paces = [s["pace_min_km"] for s in splits if s.get("pace_min_km")]
            if paces:
                fastest_split = min(paces)
                slowest_split = max(paces)
                
                fastest_km = next((s["lap_num"] for s in splits if s.get("pace_min_km") == fastest_split), None)
                slowest_km = next((s["lap_num"] for s in splits if s.get("pace_min_km") == slowest_split), None)
                
                workout["split_analysis"] = {
                    "fastest_split_pace": round(fastest_split, 2),
                    "slowest_split_pace": round(slowest_split, 2),
                    "fastest_km": fastest_km,
                    "slowest_km": slowest_km,
                    "pace_drop": round(slowest_split - fastest_split, 2),
                    "consistency_score": round(max(0, 100 - (slowest_split - fastest_split) * 10), 1),
                    "negative_split": paces[-1] < paces[0] if len(paces) >= 2 else False,
                    "total_splits": len(splits)
                }
    else:
        # No valid splits data - clear any invalid analysis
        workout["splits"] = []
        workout["split_analysis"] = {}
    
    return workout


async def process_strava_webhook_activity(athlete_id: int, activity_id: int, aspect_type: str) -> str:
    """
    Process a Strava activity event from webhook.
    1. Find the user by athlete_id
    2. Refresh token if needed
    3. Fetch the activity details
    4. Store/update in database
    """
    logger.info(f"🔄 Processing webhook activity {activity_id} for athlete {athlete_id} ({aspect_type})")
    
    # Find user by athlete_id
    token_doc = await db.strava_tokens.find_one({"athlete_id": athlete_id}, {"_id": 0})
    
    if not token_doc:
        logger.warning(f"No token found for athlete {athlete_id}")
        return "no_user_found"
    
    user_id = token_doc.get("user_id")
    access_token = token_doc.get("access_token")
    refresh_token = token_doc.get("refresh_token")
    expires_at = token_doc.get("expires_at")
    
    # Check if token is expired and refresh if needed
    if expires_at:
        current_time = datetime.now(timezone.utc).timestamp()
        if isinstance(expires_at, (int, float)) and expires_at < current_time:
            logger.info(f"Token expired for user {user_id}, refreshing...")
            try:
                new_token_data = await refresh_strava_token(refresh_token)
                access_token = new_token_data.get("access_token")
                
                # Update token in database
                await db.strava_tokens.update_one(
                    {"user_id": user_id},
                    {"$set": {
                        "access_token": new_token_data.get("access_token"),
                        "refresh_token": new_token_data.get("refresh_token", refresh_token),
                        "expires_at": new_token_data.get("expires_at")
                    }}
                )
                logger.info(f"✅ Token refreshed for user {user_id}")
            except Exception as e:
                logger.error(f"Failed to refresh token for user {user_id}: {e}")
                return "token_refresh_failed"
    
    # Fetch the activity from Strava
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                f"https://www.strava.com/api/v3/activities/{activity_id}",
                headers={"Authorization": f"Bearer {access_token}"}
            )
            response.raise_for_status()
            strava_activity = response.json()
    except httpx.HTTPStatusError as e:
        logger.error(f"Failed to fetch activity {activity_id}: {e.response.status_code}")
        return f"fetch_failed_{e.response.status_code}"
    except Exception as e:
        logger.error(f"Error fetching activity {activity_id}: {e}")
        return "fetch_error"
    
    # Convert and store the activity
    workout = convert_strava_to_workout(strava_activity, user_id)
    
    # Fetch additional details (streams, laps) for RAG enrichment
    try:
        streams_data = await fetch_strava_activity_streams(access_token, str(activity_id))
        laps_data = await fetch_strava_activity_laps(access_token, str(activity_id))
        
        # Enrich workout with detailed data
        workout = enrich_workout_with_detailed_data(workout, streams_data, laps_data)
        logger.info(f"✅ Enriched activity {activity_id} with streams and laps data")
    except Exception as e:
        logger.warning(f"Could not fetch detailed data for activity {activity_id}: {e}")
    
    # Upsert the workout
    await db.workouts.update_one(
        {"id": workout["id"]},
        {"$set": workout},
        upsert=True
    )
    
    logger.info(f"✅ Activity {activity_id} synced for user {user_id}: {workout.get('name', 'Untitled')}")
    
    # Store sync event for debugging
    await db.webhook_events.insert_one({
        "event_type": "activity_sync",
        "activity_id": activity_id,
        "athlete_id": athlete_id,
        "user_id": user_id,
        "aspect_type": aspect_type,
        "workout_name": workout.get("name"),
        "timestamp": datetime.now(timezone.utc).isoformat()
    })
    
    return "synced"


@router.get("/garmin/status")
async def get_garmin_status(user_id: str = "default"):
    """Get Garmin connection status for a user (DORMANT)"""
    # Check if user has Garmin token
    token = await db.garmin_tokens.find_one({"user_id": user_id}, {"_id": 0})
    
    if not token:
        return GarminConnectionStatus(connected=False, last_sync=None, workout_count=0)
    
    # Get last sync time and workout count
    sync_info = await db.sync_history.find_one(
        {"user_id": user_id, "source": "garmin"},
        {"_id": 0},
        sort=[("synced_at", -1)]
    )
    
    workout_count = await db.workouts.count_documents({
        "data_source": "garmin",
        "user_id": user_id
    })
    
    return GarminConnectionStatus(
        connected=True,
        last_sync=sync_info.get("synced_at") if sync_info else None,
        workout_count=workout_count
    )


@router.get("/garmin/authorize")
async def garmin_authorize():
    """Initiate Garmin OAuth flow (DORMANT)"""
    if not GARMIN_CLIENT_ID or not GARMIN_CLIENT_SECRET:
        raise HTTPException(
            status_code=503, 
            detail="Garmin integration not configured. Please add GARMIN_CLIENT_ID and GARMIN_CLIENT_SECRET to environment."
        )
    
    state = secrets.token_urlsafe(32)
    code_verifier, code_challenge = generate_pkce_pair()

    # Store PKCE pair in DB (cross-process safe), expires in 10 minutes
    await db.oauth_states.update_one(
        {"state": state},
        {"$set": {
            "state": state,
            "code_verifier": code_verifier,
            "created_at": datetime.now(timezone.utc),
            "expires_at": datetime.now(timezone.utc) + timedelta(minutes=10)
        }},
        upsert=True
    )

    auth_url = get_garmin_auth_url(code_challenge, state)
    return {"authorization_url": auth_url, "state": state}


@router.get("/garmin/callback")
async def garmin_callback(code: str, state: str):
    """Handle Garmin OAuth callback (DORMANT)"""
    pkce_entry = await db.oauth_states.find_one_and_delete({"state": state})
    if not pkce_entry:
        raise HTTPException(status_code=400, detail="Invalid state parameter")

    code_verifier = pkce_entry["code_verifier"]
    
    try:
        # Exchange code for tokens
        token_data = await exchange_garmin_code(code, code_verifier)
        access_token = token_data.get("access_token")
        refresh_token = token_data.get("refresh_token")
        expires_in = token_data.get("expires_in", 3600)
        
        user_id = "default"  # In production, get from session
        
        # Store token
        await db.garmin_tokens.update_one(
            {"user_id": user_id},
            {"$set": {
                "user_id": user_id,
                "access_token": access_token,
                "refresh_token": refresh_token,
                "expires_at": datetime.now(timezone.utc) + timedelta(seconds=expires_in),
                "created_at": datetime.now(timezone.utc).isoformat()
            }},
            upsert=True
        )
        
        logger.info(f"Garmin connected for user: {user_id}")
        
        # Redirect back to frontend settings
        return RedirectResponse(url=f"{FRONTEND_URL}/settings?garmin=connected")
    
    except Exception as e:
        logger.error(f"Garmin OAuth error: {e}")
        return RedirectResponse(url=f"{FRONTEND_URL}/settings?garmin=error")


@router.post("/garmin/sync", response_model=GarminSyncResult)
async def sync_garmin_activities(user_id: str = "default"):
    """Sync activities from Garmin Connect (DORMANT)"""
    # Get token
    token = await db.garmin_tokens.find_one({"user_id": user_id}, {"_id": 0})
    
    if not token:
        return GarminSyncResult(success=False, synced_count=0, message="Not connected to Garmin")
    
    access_token = token.get("access_token")
    
    # Check if token is expired
    expires_at = token.get("expires_at")
    if expires_at:
        if isinstance(expires_at, str):
            expires_at = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        if expires_at < datetime.now(timezone.utc):
            return GarminSyncResult(success=False, synced_count=0, message="Token expired. Please reconnect.")
    
    try:
        # Fetch activities from Garmin
        activities = await fetch_garmin_activities(access_token)
        
        synced_count = 0
        for garmin_activity in activities:
            workout = convert_garmin_to_workout(garmin_activity)
            
            if workout:
                # Check if already exists
                existing = await db.workouts.find_one({"id": workout["id"]})
                if not existing:
                    await db.workouts.insert_one(workout)
                    synced_count += 1
        
        # Record sync history
        await db.sync_history.insert_one({
            "user_id": user_id,
            "synced_at": datetime.now(timezone.utc).isoformat(),
            "synced_count": synced_count,
            "source": "garmin"
        })
        
        logger.info(f"Garmin sync complete: {synced_count} workouts for user {user_id}")
        
        return GarminSyncResult(success=True, synced_count=synced_count, message=f"Synced {synced_count} workouts")
    
    except httpx.HTTPStatusError as e:
        logger.error(f"Garmin API error: {e}")
        if e.response.status_code == 401:
            return GarminSyncResult(success=False, synced_count=0, message="Token expired. Please reconnect.")
        return GarminSyncResult(success=False, synced_count=0, message="Failed to fetch activities")
    except Exception as e:
        logger.error(f"Garmin sync error: {e}")
        return GarminSyncResult(success=False, synced_count=0, message="Sync failed")


@router.delete("/garmin/disconnect")
async def disconnect_garmin(user_id: str = "default"):
    """Disconnect Garmin account (DORMANT)"""
    await db.garmin_tokens.delete_one({"user_id": user_id})
    logger.info(f"Garmin disconnected for user: {user_id}")
    return {"success": True, "message": "Garmin disconnected"}


@router.get("/strava/status")
async def get_strava_status(user_id: str = "default"):
    """Get Strava connection status for a user"""
    # Check if user has Strava token
    token = await db.strava_tokens.find_one({"user_id": user_id}, {"_id": 0})
    
    if not token:
        return StravaConnectionStatus(connected=False, last_sync=None, workout_count=0)
    
    # Get last sync time
    sync_info = await db.sync_history.find_one(
        {"user_id": user_id, "source": "strava"},
        {"_id": 0},
        sort=[("synced_at", -1)]
    )
    
    # Count imported Strava workouts
    workout_count = await db.workouts.count_documents({
        "data_source": "strava",
        "user_id": user_id
    })
    
    return StravaConnectionStatus(
        connected=True,
        last_sync=sync_info.get("synced_at") if sync_info else None,
        workout_count=workout_count
    )


@router.get("/strava/authorize")
async def strava_authorize(user_id: str = "default"):
    """Initiate Strava OAuth flow"""
    if not STRAVA_CLIENT_ID or not STRAVA_CLIENT_SECRET:
        raise HTTPException(
            status_code=503, 
            detail="Data sync not configured. Please contact the administrator."
        )
    
    # Generate state for security
    state = secrets.token_urlsafe(32)

    # Store state with user_id in DB (cross-process safe), expires in 10 minutes
    await db.oauth_states.update_one(
        {"state": state},
        {"$set": {
            "state": state,
            "user_id": user_id,
            "provider": "strava",
            "created_at": datetime.now(timezone.utc),
            "expires_at": datetime.now(timezone.utc) + timedelta(minutes=10)
        }},
        upsert=True
    )
    
    # Build Strava authorization URL
    redirect_uri = STRAVA_REDIRECT_URI or f"{FRONTEND_URL}/settings"
    scope = "read,activity:read_all"
    
    auth_url = (
        f"https://www.strava.com/oauth/authorize"
        f"?client_id={STRAVA_CLIENT_ID}"
        f"&response_type=code"
        f"&redirect_uri={redirect_uri}"
        f"&scope={scope}"
        f"&state={state}"
    )
    
    return {"authorization_url": auth_url, "state": state}


@router.get("/strava/callback")
async def strava_callback(code: str, state: str, scope: str = None):
    """Handle Strava OAuth callback"""
    state_entry = await db.oauth_states.find_one_and_delete({"state": state, "provider": "strava"})
    if not state_entry:
        logger.warning(f"Invalid state parameter received: {state}")
        return RedirectResponse(url=f"{FRONTEND_URL}/settings?strava=error&reason=invalid_state")

    user_id = state_entry["user_id"]
    
    try:
        # Exchange code for tokens
        token_data = await exchange_strava_code(code)
        access_token = token_data.get("access_token")
        refresh_token = token_data.get("refresh_token")
        expires_at = token_data.get("expires_at")  # Strava returns Unix timestamp
        athlete_info = token_data.get("athlete", {})
        
        # Store token
        await db.strava_tokens.update_one(
            {"user_id": user_id},
            {"$set": {
                "user_id": user_id,
                "access_token": access_token,
                "refresh_token": refresh_token,
                "expires_at": expires_at,
                "athlete_id": athlete_info.get("id"),
                "created_at": datetime.now(timezone.utc).isoformat()
            }},
            upsert=True
        )
        
        logger.info(f"Strava connected for user: {user_id}, athlete: {athlete_info.get('id')}")
        
        # Redirect back to frontend settings
        return RedirectResponse(url=f"{FRONTEND_URL}/settings?strava=connected")
    
    except httpx.HTTPStatusError as e:
        logger.error(f"Strava OAuth HTTP error: {e.response.status_code} - {e.response.text}")
        return RedirectResponse(url=f"{FRONTEND_URL}/settings?strava=error&reason=token_exchange_failed")
    except Exception as e:
        logger.error(f"Strava OAuth error: {e}")
        return RedirectResponse(url=f"{FRONTEND_URL}/settings?strava=error&reason=unknown")


@router.post("/strava/sync", response_model=StravaSyncResult)
async def sync_strava_activities(user_id: str = "default", fetch_details: bool = True):
    """Sync activities from Strava with detailed HR/pace/splits data for RAG"""
    # Get token
    token = await db.strava_tokens.find_one({"user_id": user_id}, {"_id": 0})
    
    if not token:
        return StravaSyncResult(success=False, synced_count=0, message="Not connected to Strava")
    
    access_token = token.get("access_token")
    refresh_token = token.get("refresh_token")
    expires_at = token.get("expires_at")
    
    # Check if token is expired and refresh if needed
    if expires_at:
        if isinstance(expires_at, (int, float)):
            token_expired = expires_at < datetime.now(timezone.utc).timestamp()
        else:
            token_expired = False
            
        if token_expired and refresh_token:
            try:
                # Refresh the token
                new_token_data = await refresh_strava_token(refresh_token)
                access_token = new_token_data.get("access_token")
                
                # Update stored token
                await db.strava_tokens.update_one(
                    {"user_id": user_id},
                    {"$set": {
                        "access_token": new_token_data.get("access_token"),
                        "refresh_token": new_token_data.get("refresh_token"),
                        "expires_at": new_token_data.get("expires_at")
                    }}
                )
                logger.info(f"Strava token refreshed for user: {user_id}")
            except Exception as e:
                logger.error(f"Failed to refresh Strava token: {e}")
                return StravaSyncResult(success=False, synced_count=0, message="Token expired. Please reconnect.")
    
    try:
        # Fetch activities from Strava
        activities = await fetch_strava_activities(access_token, per_page=100)
        
        synced_count = 0
        detailed_count = 0
        
        for idx, strava_activity in enumerate(activities):
            activity_id = strava_activity.get("id")
            
            # Fetch detailed data for recent activities (first 50 for better RAG)
            streams_data = None
            zones_data = None
            laps_data = None
            
            if fetch_details and idx < 50 and activity_id:
                # Fetch laps (splits) for all activities
                laps_data = await fetch_strava_activity_laps(access_token, str(activity_id))
                
                # Fetch streams and zones for activities with HR data
                if strava_activity.get("has_heartrate") or strava_activity.get("average_heartrate"):
                    streams_data = await fetch_strava_activity_streams(access_token, str(activity_id))
                    zones_data = await fetch_strava_activity_zones(access_token, str(activity_id))
                
                if streams_data or zones_data or laps_data:
                    detailed_count += 1
            
            # Convert base workout
            workout = convert_strava_to_workout(strava_activity, streams_data, zones_data)
            
            if workout:
                # Enrich with detailed data (splits, HR analysis, cadence analysis)
                workout = enrich_workout_with_detailed_data(workout, streams_data, laps_data)
                
                # Check if already exists
                existing = await db.workouts.find_one({"id": workout["id"]})
                if not existing:
                    await db.workouts.insert_one(workout)
                    synced_count += 1
                else:
                    # Update existing workout with new detailed data
                    update_fields = {}
                    
                    # Basic fields
                    for field in ["effort_zone_distribution", "pace_stats", "best_pace_min_km", "avg_cadence_spm"]:
                        if workout.get(field):
                            update_fields[field] = workout[field]
                    
                    # Detailed data for RAG
                    for field in ["splits", "split_analysis", "km_splits", "hr_analysis", 
                                  "cadence_analysis", "elevation_analysis", 
                                  "hr_stream_sample", "cadence_stream_sample"]:
                        if workout.get(field):
                            update_fields[field] = workout[field]
                    
                    if update_fields:
                        await db.workouts.update_one(
                            {"id": workout["id"]},
                            {"$set": update_fields}
                        )
        
        # Record sync history
        await db.sync_history.insert_one({
            "user_id": user_id,
            "synced_at": datetime.now(timezone.utc).isoformat(),
            "synced_count": synced_count,
            "detailed_count": detailed_count,
            "source": "strava"
        })
        
        logger.info(f"Strava sync complete: {synced_count} new workouts, {detailed_count} with detailed data for user {user_id}")
        
        message = f"Synced {synced_count} workouts"
        if detailed_count > 0:
            message += f" ({detailed_count} with detailed HR/pace data)"
        
        return StravaSyncResult(success=True, synced_count=synced_count, message=message)
    
    except httpx.HTTPStatusError as e:
        logger.error(f"Strava API error: {e.response.status_code} - {e.response.text}")
        if e.response.status_code == 401:
            return StravaSyncResult(success=False, synced_count=0, message="Token expired. Please reconnect.")
        return StravaSyncResult(success=False, synced_count=0, message="Failed to fetch activities")
    except Exception as e:
        logger.error(f"Strava sync error: {e}")
        return StravaSyncResult(success=False, synced_count=0, message="Sync failed")


@router.delete("/strava/disconnect")
async def disconnect_strava(user_id: str = "default"):
    """Disconnect Strava account"""
    await db.strava_tokens.delete_one({"user_id": user_id})
    logger.info(f"Strava disconnected for user: {user_id}")
    return {"success": True, "message": "Strava disconnected"}


@router.get("/webhooks/strava")
async def strava_webhook_verify(
    request: Request,
):
    """
    Handle Strava webhook verification (GET request).
    Strava sends: hub.mode=subscribe, hub.verify_token, hub.challenge
    We must return: {"hub.challenge": <challenge_value>}
    """
    params = dict(request.query_params)
    hub_mode = params.get("hub.mode")
    hub_verify_token = params.get("hub.verify_token")
    hub_challenge = params.get("hub.challenge")
    
    logger.info(f"Strava webhook verification: mode={hub_mode}, token={hub_verify_token}, challenge={hub_challenge}")
    
    if hub_mode == "subscribe" and hub_verify_token == STRAVA_WEBHOOK_VERIFY_TOKEN:
        logger.info("✅ Strava webhook verification successful")
        return {"hub.challenge": hub_challenge}
    else:
        logger.warning(f"❌ Strava webhook verification failed: invalid token or mode")
        raise HTTPException(status_code=403, detail="Verification failed")


@router.post("/webhooks/strava")
async def strava_webhook_event(request: Request):
    """
    Handle Strava webhook events (POST request).
    Strava sends events for activity create/update/delete, athlete update/deauthorize.
    """
    try:
        event = await request.json()
    except Exception as e:
        logger.error(f"Failed to parse webhook event: {e}")
        return {"status": "error", "message": "Invalid JSON"}
    
    object_type = event.get("object_type")  # "activity" or "athlete"
    aspect_type = event.get("aspect_type")  # "create", "update", "delete"
    object_id = event.get("object_id")  # activity_id or athlete_id
    owner_id = event.get("owner_id")  # athlete_id (owner of the object)
    subscription_id = event.get("subscription_id")
    event_time = event.get("event_time")
    updates = event.get("updates", {})  # For update events, contains changed fields
    
    logger.info(f"📩 Strava webhook event: type={object_type}, aspect={aspect_type}, object_id={object_id}, owner_id={owner_id}")
    
    # Handle athlete deauthorization
    if object_type == "athlete" and aspect_type == "update" and updates.get("authorized") == "false":
        logger.info(f"🔒 Athlete {owner_id} deauthorized - removing tokens")
        await db.strava_tokens.delete_one({"athlete_id": owner_id})
        return {"status": "ok", "action": "deauthorized"}
    
    # Handle activity events
    if object_type == "activity":
        if aspect_type in ["create", "update"]:
            # Process the activity asynchronously
            try:
                result = await process_strava_webhook_activity(owner_id, object_id, aspect_type)
                return {"status": "ok", "action": result}
            except Exception as e:
                logger.error(f"Error processing activity {object_id}: {e}")
                return {"status": "error", "message": str(e)}
        
        elif aspect_type == "delete":
            # Delete the activity from our database
            logger.info(f"🗑️ Deleting activity {object_id} from webhook")
            await db.workouts.delete_one({"id": f"strava_{object_id}"})
            return {"status": "ok", "action": "deleted"}
    
    # Acknowledge other events
    return {"status": "ok", "action": "ignored"}


@router.post("/strava/webhook/subscribe", response_model=WebhookSubscriptionResponse)
async def create_strava_webhook_subscription(req: WebhookSubscriptionRequest):
    """
    Create a Strava webhook subscription (admin endpoint).
    This should be called once to register the webhook with Strava.
    """
    client_id = os.environ.get("STRAVA_CLIENT_ID")
    client_secret = os.environ.get("STRAVA_CLIENT_SECRET")
    
    if not client_id or not client_secret:
        return WebhookSubscriptionResponse(
            success=False,
            message="Missing STRAVA_CLIENT_ID or STRAVA_CLIENT_SECRET"
        )
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                "https://www.strava.com/api/v3/push_subscriptions",
                data={
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "callback_url": req.callback_url,
                    "verify_token": STRAVA_WEBHOOK_VERIFY_TOKEN
                }
            )
            
            if response.status_code == 201:
                data = response.json()
                subscription_id = data.get("id")
                
                # Store subscription info
                await db.strava_webhook_subscriptions.update_one(
                    {"type": "main"},
                    {"$set": {
                        "subscription_id": subscription_id,
                        "callback_url": req.callback_url,
                        "created_at": datetime.now(timezone.utc).isoformat()
                    }},
                    upsert=True
                )
                
                logger.info(f"✅ Strava webhook subscription created: {subscription_id}")
                return WebhookSubscriptionResponse(
                    success=True,
                    subscription_id=subscription_id,
                    message="Webhook subscription created successfully"
                )
            else:
                error_msg = response.text
                logger.error(f"Failed to create webhook subscription: {response.status_code} - {error_msg}")
                return WebhookSubscriptionResponse(
                    success=False,
                    message=f"Failed: {error_msg}"
                )
    except Exception as e:
        logger.error(f"Error creating webhook subscription: {e}")
        return WebhookSubscriptionResponse(
            success=False,
            message=str(e)
        )


@router.get("/strava/webhook/status")
async def get_strava_webhook_status():
    """Get current Strava webhook subscription status"""
    client_id = os.environ.get("STRAVA_CLIENT_ID")
    client_secret = os.environ.get("STRAVA_CLIENT_SECRET")
    
    if not client_id or not client_secret:
        return {"status": "error", "message": "Missing credentials"}
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                "https://www.strava.com/api/v3/push_subscriptions",
                params={
                    "client_id": client_id,
                    "client_secret": client_secret
                }
            )
            
            if response.status_code == 200:
                subscriptions = response.json()
                
                # Get recent webhook events from our DB
                recent_events = await db.webhook_events.find(
                    {},
                    {"_id": 0}
                ).sort("timestamp", -1).limit(10).to_list(10)
                
                return {
                    "status": "ok",
                    "subscriptions": subscriptions,
                    "recent_events": recent_events,
                    "verify_token_configured": bool(STRAVA_WEBHOOK_VERIFY_TOKEN)
                }
            else:
                return {
                    "status": "error",
                    "message": response.text
                }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.delete("/strava/webhook/unsubscribe/{subscription_id}")
async def delete_strava_webhook_subscription(subscription_id: int):
    """Delete a Strava webhook subscription"""
    client_id = os.environ.get("STRAVA_CLIENT_ID")
    client_secret = os.environ.get("STRAVA_CLIENT_SECRET")
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.delete(
                f"https://www.strava.com/api/v3/push_subscriptions/{subscription_id}",
                params={
                    "client_id": client_id,
                    "client_secret": client_secret
                }
            )
            
            if response.status_code == 204:
                await db.strava_webhook_subscriptions.delete_one({"subscription_id": subscription_id})
                logger.info(f"✅ Webhook subscription {subscription_id} deleted")
                return {"success": True, "message": "Subscription deleted"}
            else:
                return {"success": False, "message": response.text}
    except Exception as e:
        return {"success": False, "message": str(e)}
