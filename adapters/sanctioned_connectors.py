
SANCTIONED_CONNECTORS = [
    {
        "connector_name": "tn_cctns_citizen_portal",
        "source_type": "citizen_portal",
        "base_url": "https://eservices.tnpolice.gov.in/CCTNSNICSDC/",
        "sanctioned": True,
        "access_mode": "public_web",
        "notes": "Public citizen-facing portal; no privileged API assumed in MVP.",
    },
    {
        "connector_name": "national_cybercrime_portal",
        "source_type": "cybercrime_intake",
        "base_url": "https://cybercrime.gov.in/",
        "sanctioned": True,
        "access_mode": "public_web",
        "notes": "Public cybercrime intake portal; adapter is registry-first.",
    },
    {
        "connector_name": "tn_public_cctv_event_feed",
        "source_type": "cctv_event_stream",
        "base_url": None,
        "sanctioned": False,
        "access_mode": "not_open",
        "notes": "No public statewide event stream available; demo-only feed unless agency access exists.",
    },
    {
        "connector_name": "patrol_reporting_ingest",
        "source_type": "patrol_reporting",
        "base_url": None,
        "sanctioned": True,
        "access_mode": "internal_app",
        "notes": "Internal reporting channel scaffolded for operator-entry and future mobile client.",
    },
]
