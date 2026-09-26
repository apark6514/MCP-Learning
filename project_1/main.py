"""Fetch live flight data from the OpenSky Network API and print it as a readable table.

API docs: https://openskynetwork.github.io/opensky-api/rest.html
No API key is needed for anonymous requests (they are rate-limited).
"""

from datetime import datetime

import requests

BASE_URL = "https://opensky-network.org/api"


def get_flights_in_area(lat_min, lon_min, lat_max, lon_max):
    """Return live flight data (as a dict) for aircraft inside a lat/lon bounding box."""
    url = f"{BASE_URL}/states/all"
    params = {
        "lamin": lat_min,
        "lomin": lon_min,
        "lamax": lat_max,
        "lomax": lon_max,
    }

    response = requests.get(url, params=params, timeout=15)
    response.raise_for_status()  # raise an error for 4xx/5xx status codes
    return response.json()  # parse the JSON body into Python dicts/lists


def parse_flights(data):
    """Turn the raw API response into a list of dicts with named fields.

    Each flight in data["states"] is a list where the position of each value
    tells you what it means (index 1 is the callsign, 7 is altitude, etc.).
    """
    flights = []
    for state in data.get("states") or []:  # "states" is null when no flights are found
        flights.append({
            "icao24": state[0],
            "callsign": (state[1] or "").strip() or "N/A",
            "country": state[2],
            "longitude": state[5],
            "latitude": state[6],
            "altitude_m": state[7],
            "on_ground": state[8],
            "speed_ms": state[9],
            "heading": state[10],
        })
    return flights


def format_flight(flight):
    """Return one flight as a single readable line."""
    if flight["on_ground"]:
        altitude = "on ground"
    elif flight["altitude_m"] is not None:
        altitude = f"{flight['altitude_m'] * 3.28084:,.0f} ft"
    else:
        altitude = "unknown"

    speed = f"{flight['speed_ms'] * 1.94384:.0f} kt" if flight["speed_ms"] is not None else "unknown"
    heading = f"{flight['heading']:.0f}°" if flight["heading"] is not None else "unknown"

    return (
        f"{flight['callsign']:<10} {flight['country']:<22} "
        f"{altitude:>11} {speed:>8} {heading:>8}"
    )


def main():
    # Bounding box around Switzerland
    try:
        data = get_flights_in_area(45.8, 5.9, 47.8, 10.5)
    except requests.exceptions.RequestException as error:
        print(f"Could not fetch flight data: {error}")
        return

    flights = parse_flights(data)
    snapshot_time = datetime.fromtimestamp(data["time"]).strftime("%Y-%m-%d %H:%M:%S")

    print(f"{len(flights)} flights over Switzerland at {snapshot_time}\n")
    print(f"{'CALLSIGN':<10} {'COUNTRY':<22} {'ALTITUDE':>11} {'SPEED':>8} {'HEADING':>8}")
    print("-" * 63)
    for flight in sorted(flights, key=lambda f: f["callsign"]):
        print(format_flight(flight))


if __name__ == "__main__":
    main()
