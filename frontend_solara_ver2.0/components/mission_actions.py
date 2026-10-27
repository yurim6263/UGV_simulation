import threading

from components.state import (
    ARRIVAL_TIMES_BY_MODE,
    active_btn,
    asset_data,
    mission_delivery_data,
    departure_times,
    mission_settings,
    toast_trigger,
)

from services.api_client import post_operator_mission_config

def deliver_mission():
    current_arrival_times = ARRIVAL_TIMES_BY_MODE.get(active_btn.value, {})

    mission_delivery_data.value = {
        "delivered": True,
        "base_summary": {
            "total_units": asset_data.value.get("base", {}).get("total_units", 0),
            "total_controllers": asset_data.value.get("base", {}).get("total_controllers", 0),
            "total_recon_ugv": asset_data.value.get("base", {}).get("total_ugv", 0),
            "total_lost_ugv": asset_data.value.get("base", {}).get("lost_ugv", 0),
        },
        "units": {
            u: {
                "controllers": asset_data.value.get(u, {}).get("controllers", 0),
                "total_recon_ugv": asset_data.value.get(u, {}).get("total_ugv", 0),
                "lost_ugv": asset_data.value.get(u, {}).get("lost_ugv", 0),
                "available_ugv": asset_data.value.get(u, {}).get("available_ugv", 0),
                "target_lat": asset_data.value.get(u, {}).get("target_lat", ""),
                "target_lon": asset_data.value.get(u, {}).get("target_lon", ""),
            }
            for u in ("user1", "user2", "user3")
        },
        "mission_info": {
            u: {
                "mission_mode": active_btn.value,
                "operating_ugv_count": asset_data.value.get(u, {}).get("available_ugv", 0),
                "departure_time": departure_times.value.get(u, ""),
                "arrival_time": current_arrival_times.get(u, ""),
                "recon_time": mission_settings.value.get("recon_times", {}).get(u, ""),
            }
            for u in ("user1", "user2", "user3")
        },
    }

    threading.Thread(target=post_operator_mission_config, daemon=True).start()
    toast_trigger.value += 1