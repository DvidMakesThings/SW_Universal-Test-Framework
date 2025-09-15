"""
Hardware Configuration for PCAPGen/Analyzer Test
================================================
Values consumed by tc_pcap_create / tc_network_pcapgen tests via get_hwconfig().
"""

# ---------------- Paths ----------------
PCAP_OUTPUT_DIR = "report_tc_pcap_create"
PCAP_FILENAME = "test_pcap.pcap"

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
