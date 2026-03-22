
def can_write_case(role_name: str) -> bool:
    return role_name in {"admin", "cyber_analyst", "district_sp"}

def can_assign_case(role_name: str) -> bool:
    return role_name in {"admin", "district_sp"}

def can_comment_case(role_name: str) -> bool:
    return role_name in {"admin", "cyber_analyst", "district_sp"}

def can_manage_watchlist(role_name: str) -> bool:
    return role_name in {"admin", "cyber_analyst", "district_sp"}

def can_add_evidence(role_name: str) -> bool:
    return role_name in {"admin", "cyber_analyst", "district_sp"}
