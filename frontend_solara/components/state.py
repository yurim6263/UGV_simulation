import solara

workflowstep = solara.reactive(0)
################# 실행/종료 버튼으로 타이머 역할 하기 ######################

timer_running = solara.reactive(False)
timer_end_ts = solara.reactive(None)
remaining_time_text_global = solara.reactive("02:20:00")
# 가상 잔여 초 — clock_loop이 0.5초마다 600씩 감산 (14틱×0.5s=7s, 14×600=8400)
timer_remaining_secs = solara.reactive(8400)   # 2시간 20분 = 8400초

# 영상 재생 제어 — True: 실행 중 (play), False: 정지
video_should_play = solara.reactive(False)

# 임무하달 버튼
toast_trigger = solara.reactive(0)

selected_mission_mode = solara.reactive("")

mission_toast_count = solara.reactive(0)
mission_toast_message = solara.reactive("")


active_btn = solara.reactive(None)

asset_data = solara.reactive({
    "base": {
        "total_units": 3,
        "total_controllers": 3,
        "total_ugv": 13,
        "lost_ugv": 1,
    },
    "user1": {
        "controllers": 1,
        "total_ugv": 4,
        "lost_ugv": 0,
        "available_ugv": 4,
        "target_lat": "",
        "target_lon": "",
    },
    "user2": {
        "controllers": 1,
        "total_ugv": 5,
        "lost_ugv": 1,
        "available_ugv": 4,
        "target_lat": "",
        "target_lon": "",
    },
    "user3": {
        "controllers": 1,
        "total_ugv": 4,
        "lost_ugv": 0,
        "available_ugv": 4,
        "target_lat": "",
        "target_lon": "",
    },
})

mission_settings = solara.reactive({
    "recon_times": {
        "user1": "",
        "user2": "",
        "user3": "",
    }
})

mission_delivery_data = solara.reactive({
    "delivered": False,
    "base_summary": {
        "total_units": 0,
        "total_controllers": 0,
        "total_recon_ugv": 0,
        "total_lost_ugv": 0,
    },
    "units": {
        "user1": {"controllers": 0, "total_recon_ugv": 0, "lost_ugv": 0, "available_ugv": 0, "target_lat": "", "target_lon": ""},
        "user2": {"controllers": 0, "total_recon_ugv": 0, "lost_ugv": 0, "available_ugv": 0, "target_lat": "", "target_lon": ""},
        "user3": {"controllers": 0, "total_recon_ugv": 0, "lost_ugv": 0, "available_ugv": 0, "target_lat": "", "target_lon": ""},
    },
    "mission_info": {
        "user1": {"mission_mode": "", "operating_ugv_count": 0, "departure_time": "", "arrival_time": "", "recon_time": ""},
        "user2": {"mission_mode": "", "operating_ugv_count": 0, "departure_time": "", "arrival_time": "", "recon_time": ""},
        "user3": {"mission_mode": "", "operating_ugv_count": 0, "departure_time": "", "arrival_time": "", "recon_time": ""},
    },
})

departure_times = solara.reactive({
    "user1": None,
    "user2": None,
    "user3": None,
})

ARRIVAL_TIMES_BY_MODE = {
    "균형": {
        "user1": "05:20:00",
        "user2": "05:50:00",
        "user3": "06:10:00",
    },
    "신속": {
        "user1": "05:30:00",
        "user2": "05:20:00",
        "user3": "06:00:00",
    },
    "정밀": {
        "user1": "06:10:00",
        "user2": "06:00:00",
        "user3": "04:50:00",
    },
}

MISSION_UGV_PLAN_BY_MODE = {
    "균형": {
        "user1": 2,
        "user2": 4,
        "user3": 3,
    },
    "정밀": {
        "user1": 4,
        "user2": 2,
        "user3": 3,
    },
    "신속": {
        "user1": 4,
        "user2": 1,
        "user3": 4,
    },
}

operating_ugv_plan = solara.reactive({
    "user1": None,
    "user2": None,
    "user3": None,
})


DEST_INFO_BY_MODE = {
    "균형": {
        "1제대": "도착지3",
        "2제대": "도착지1",
        "3제대": "도착지2",
    },
    "신속": {
        "1제대": "도착지1",
        "2제대": "도착지2",
        "3제대": "도착지3",
    },
    "정밀": {
        "1제대": "도착지1",
        "2제대": "도착지2",
        "3제대": "도착지3",
    },
}