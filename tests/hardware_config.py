"""
ENERGIS Hardware Configuration
==============================
Hardware-specific configuration for ENERGIS device testing
"""

# Network Configuration
BASELINE_IP = "192.168.0.11"
BASELINE_SUBNET = "255.255.255.0"
BASELINE_GATEWAY = "192.168.0.1"
BASELINE_DNS = "8.8.8.8"
SNMP_COMMUNITY = "public"
HTTP_TIMEOUT = 3.0
HTTP_PORT = 80  # Added: used by Ethernet tests to build base URL
TEMP_NEW_IP = "192.168.0.72"  # Added: temporary IP used by IP change/revert test

# Web UI paths & dumps (used by universal Ethernet test)
CONTROL_PATH = "/control"     # Added: form endpoint for outlet control
SETTINGS_PATH = "/settings"   # Added: form endpoint for network settings

# Serial Configuration
SERIAL_PORT = "COM11"
BAUDRATE = 115200
SERIAL_TIMEOUT = 3.0
WRITE_TIMEOUT = 1.0

# SNMP OIDs
ENTERPRISE_OID = "1.3.6.1.4.1.19865"
OUTLET_BASE_OID = "1.3.6.1.4.1.19865.2"
ALL_ON_OID = "1.3.6.1.4.1.19865.2.10.0"
ALL_OFF_OID = "1.3.6.1.4.1.19865.2.9.0"
SNMP_TIMEOUT = 3.0

# System OIDs
SYS_DESCR = "1.3.6.1.2.1.1.1.0"
SYS_OBJID = "1.3.6.1.2.1.1.2.0"
SYS_UPTIME = "1.3.6.1.2.1.1.3.0"
SYS_CONTACT = "1.3.6.1.2.1.1.4.0"
SYS_NAME = "1.3.6.1.2.1.1.5.0"
SYS_LOCATION = "1.3.6.1.2.1.1.6.0"
SYS_SERVICES = "1.3.6.1.2.1.1.7.0"

# Network OIDs
NET_IP_OID = "1.3.6.1.4.1.19865.4.1.0"
NET_SN_OID = "1.3.6.1.4.1.19865.4.2.0"
NET_GW_OID = "1.3.6.1.4.1.19865.4.3.0"
NET_DNS_OID = "1.3.6.1.4.1.19865.4.4.0"

# Long-length test OIDs
LONG_LENGTH_TEST_1 = "1.3.6.1.4.1.19865.1.0"
LONG_LENGTH_TEST_2 = "1.3.6.1.4.1.19865.2.0"

# Commands
HELP_CMD = "HELP"
SYSINFO_CMD = "SYSINFO"
NETINFO_CMD = "NETINFO"
REBOOT_CMD = "REBOOT"
RFS_CMD = "RFS"
DUMP_EEPROM_CMD = "DUMP_EEPROM"
SET_IP_CMD = "SET_IP"
SET_GW_CMD = "SET_GW"
SET_SN_CMD = "SET_SN"
SET_DNS_CMD = "SET_DNS"
SET_CH_CMD = "SET_CH"
GET_CH_CMD = "GET_CH"

# Validation Rules
HELP_TOKENS = [
    "HELP",
    "SYSINFO",
    "REBOOT",
    "BOOTSEL",
    "CONFIG_NETWORK",
    "SET_IP",
    "SET_DNS",
    "SET_GW",
    "SET_SN",
    "NETINFO",
    "SET_CH",
    "READ_HLW8032",
    "READ_HLW8032 <ch>",
    "DUMP_EEPROM",
    "RFS"
]

FIRMWARE_REGEX = r"^\d+\.\d+\.\d+(?:[-+].*)?$"
CORE_VOLTAGE_RANGE = [0.9, 1.5]

# Frequency expectations
SYS_HZ_MIN = 100000000
USB_HZ_EXPECT = 48000000
PER_HZ_EXPECT = 48000000
ADC_HZ_EXPECT = 48000000

# System Info Expected Values
SYS_DESCR_EXPECTED = "^ENERGIS 8 CHANNEL MANAGED PDU$"
SYS_CONTACT_EXPECTED = "^dvidmakesthings@gmail.com$"
SYS_NAME_EXPECTED = r"^SN-[A-Za-z0-9]{10,}.*$"
SYS_LOCATION_EXPECTED = "^Wien$"
SYS_SERVICES_EXPECTED = "^-?5$"

# Long-length test expectations
LONG_LENGTH_1_EXPECTED = "^long-length OID Test #1$"
LONG_LENGTH_2_ERROR_EXPECTED = True  # Should produce noSuchName error

# ---------------- Paths ----------------
PCAP_OUTPUT_DIR = "report_tc_pcap_create"
PCAP_FILENAME = "test_pcap.pcap"
PCAPCAPTURE_OUTPUT_DIR = "report_tc_pcap_capture"
PCAP_CAPTURE_FILENAME = "capture_test.pcap"

# ---------------- MAC addresses ----------------
MAC_A = "aa:bb:cc:dd:ee:01"  # dst
MAC_B = "aa:bb:cc:dd:ee:02"  # src

# ---------------- Ethernet ----------------
ETHERTYPE = 0x88B6
LINK_SPEED_BPS = "1G"  # 1 Gbps
IFG_BYTES = 12  # 12B IFG at 1G -> 96 ns end-to-start

# Precomputed expected pair delta for IFG12B_Timing step:
# 128B tx time @1G = 1024 ns, + 12B IFG (96 ns) = 1120 ns first-to-first
IFG12B_PAIR_DELTA_NS = 1120

# Optional (not strictly required by current test, but useful if referenced)
FCS_XORMASK = 0xDEADBEEF

# ---------------- Step: UDP128 ----------------
UDP128_SRC_IP = "192.0.2.1"
UDP128_DST_IP = "198.51.100.1"
UDP128_SRC_PORT = 1369
UDP128_DST_PORT = 63357

# ---------------- Step: IPv4FragManual300 ----------------
FRAG_MANUAL_SRC_IP = "192.0.2.10"
FRAG_MANUAL_DST_IP = "198.51.100.20"

# ---------------- Step: UDPFragAuto ----------------
FRAG_AUTO_SRC_IP = "10.0.0.1"
FRAG_AUTO_DST_IP = "10.0.0.2"
FRAG_AUTO_SRC_PORT = 38055
FRAG_AUTO_DST_PORT = 14635

# Expected frame lengths for UDP fragmentation check
UDPFRAG_EXPECTED_LENS = [638, 638, 246]
