"""Constants for the Canada GreenButton integration."""
from __future__ import annotations

DOMAIN = "canada_greenbutton"
PLATFORMS = ["sensor"]

STORAGE_VERSION = 1
STORAGE_KEY = DOMAIN

# ESPI Units of Measurement
UOM_KWH = 72
UOM_CAD = 80
UOM_M3 = 167
UOM_THERMS = 169
UOM_FT3 = 119

UOM_LABELS = {
    UOM_KWH: "kWh",
    UOM_CAD: "CAD",
    UOM_M3: "m³",
    UOM_THERMS: "therms",
    UOM_FT3: "ft³",
}

# Time-of-Use tiers (Alectra encoding)
TOU_ON = 1
TOU_MID = 2
TOU_OFF = 3

# Filters
MIN_GAS_DURATION_S = 7 * 86400
HOUR_S = 3600

# Charge note keywords (case-insensitive substring match)
CHARGE_DELIVERY = "delivery charge"
CHARGE_REGULATORY = "regulatory charge"
CHARGE_HST = "hst"
CHARGE_ONTARIO_REBATE = "ontario electricity rebate"
CHARGE_GAS_SUPPLY = "gas supply"
CHARGE_GAS_DELIVERY = "gas delivery"
CHARGE_CARBON = "federal carbon"
NOTE_USAGE_UNADJUSTED = "usage (unadjusted)"

# Sources
SOURCE_ALECTRA = "alectra"
SOURCE_ENBRIDGE = "enbridge"
SOURCE_GENERIC = "generic"
SOURCE_AUTO = "auto"

# Config / options keys
CONF_WATCH_DIR = "watch_dir"
CONF_PUSH_STATS = "push_statistics"
CONF_UPLOAD_PATH = "upload_path"
CONF_DEFAULT_TZ = "timezone"
DEFAULT_TZ = "America/Toronto"

# Services
SERVICE_IMPORT_XML = "import_xml"
SERVICE_CLEAR_DATA = "clear_data"

# Statistic id prefixes
STAT_PREFIX = "canada_greenbutton"

WATCH_INTERVAL_S = 60
IMPORT_DIR = "canada_greenbutton"
