"""NMEA-0183 GPS Sentence Parser.

Parses $GPGGA and $GPRMC sentences from UART serial GPS receivers (e.g. u-blox),
validates NMEA XOR checksums, and converts coordinates to decimal degrees.
"""

from datetime import UTC, datetime
from typing import NamedTuple


class ParsedNmeaFix(NamedTuple):
    """Normalized output from an NMEA sentence."""

    timestamp: datetime
    latitude: float
    longitude: float
    altitude_m: float
    circular_error_m: float
    speed_mps: float | None = None
    heading_deg: float | None = None
    fix_quality: int = 1


def verify_nmea_checksum(sentence: str) -> bool:
    """Validate NMEA XOR checksum (*XX)."""
    sentence = sentence.strip()
    if not sentence.startswith("$") or "*" not in sentence:
        return False

    body, checksum_hex = sentence[1:].split("*", 1)
    if len(checksum_hex) < 2:
        return False

    calculated_checksum = 0
    for char in body:
        calculated_checksum ^= ord(char)

    try:
        expected_checksum = int(checksum_hex[:2], 16)
        return calculated_checksum == expected_checksum
    except ValueError:
        return False


def _nmea_to_decimal(raw_coord: str, direction: str) -> float | None:
    """Convert NMEA ddmm.mmmm format to decimal degrees."""
    if not raw_coord or not direction:
        return None

    try:
        dot_idx = raw_coord.find(".")
        if dot_idx < 0:
            return None

        # Degrees are the digits before the last 2 digits before the decimal point
        deg_len = dot_idx - 2
        if deg_len <= 0:
            return None

        degrees = float(raw_coord[:deg_len])
        minutes = float(raw_coord[deg_len:])
        decimal = degrees + (minutes / 60.0)

        if direction.upper() in ("S", "W"):
            decimal = -decimal

        return decimal
    except ValueError:
        return None


def parse_nmea_sentence(sentence: str) -> ParsedNmeaFix | None:
    """Parse a single NMEA sentence ($GPGGA, $GNGGA, $GPRMC, $GNRMC).

    Returns:
        ParsedNmeaFix if valid fix is extracted, or None.
    """
    sentence = sentence.strip()
    if not sentence.startswith("$") or not verify_nmea_checksum(sentence):
        return None

    content = sentence[1:].split("*")[0]
    tokens = content.split(",")
    talker = tokens[0]

    now_utc = datetime.now(UTC)

    if talker in ("GPGGA", "GNGGA"):
        # Format: $GPGGA,hhmmss.ss,llll.ll,a,yyyyy.yy,a,x,xx,x.x,x.x,M,x.x,M,x.x,xxxx*hh
        if len(tokens) < 10:
            return None

        raw_lat = tokens[2]
        lat_dir = tokens[3]
        raw_lon = tokens[4]
        lon_dir = tokens[5]
        fix_quality_str = tokens[6]
        hdop_str = tokens[8]
        alt_str = tokens[9]

        try:
            fix_quality = int(fix_quality_str) if fix_quality_str else 0
            if fix_quality == 0:
                # No GPS fix
                return None

            lat = _nmea_to_decimal(raw_lat, lat_dir)
            lon = _nmea_to_decimal(raw_lon, lon_dir)
            if lat is None or lon is None:
                return None

            altitude_m = float(alt_str) if alt_str else 0.0

            # Convert HDOP to estimated Circular Error (1-sigma ~ HDOP * 2.5m nominal baseline)
            hdop = float(hdop_str) if hdop_str else 2.0
            circular_error_m = max(1.0, round(hdop * 2.5, 2))

            return ParsedNmeaFix(
                timestamp=now_utc,
                latitude=round(lat, 7),
                longitude=round(lon, 7),
                altitude_m=round(altitude_m, 2),
                circular_error_m=circular_error_m,
                fix_quality=fix_quality,
            )
        except (ValueError, IndexError):
            return None

    elif talker in ("GPRMC", "GNRMC"):
        # Format: $GPRMC,hhmmss.ss,A,llll.ll,a,yyyyy.yy,a,x.x,x.x,ddmmyy,,,a*hh
        if len(tokens) < 9:
            return None

        status = tokens[2]
        if status.upper() != "A":  # 'A' = Active/Valid fix, 'V' = Void/Invalid
            return None

        raw_lat = tokens[3]
        lat_dir = tokens[4]
        raw_lon = tokens[5]
        lon_dir = tokens[6]
        speed_knots_str = tokens[7]
        course_str = tokens[8]

        try:
            lat = _nmea_to_decimal(raw_lat, lat_dir)
            lon = _nmea_to_decimal(raw_lon, lon_dir)
            if lat is None or lon is None:
                return None

            # 1 knot = 0.514444 m/s
            speed_mps = round(float(speed_knots_str) * 0.514444, 2) if speed_knots_str else 0.0
            course_deg = round(float(course_str), 1) if course_str else 0.0

            return ParsedNmeaFix(
                timestamp=now_utc,
                latitude=round(lat, 7),
                longitude=round(lon, 7),
                altitude_m=0.0,
                circular_error_m=3.0,
                speed_mps=speed_mps,
                heading_deg=course_deg,
                fix_quality=1,
            )
        except (ValueError, IndexError):
            return None

    return None
