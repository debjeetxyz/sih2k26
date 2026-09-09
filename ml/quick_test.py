from inference import run_inference

test_frame = {
    "timestamp": 0.0,
    "cyl_1_temp": 120.0, "cyl_2_temp": 120.1, "cyl_3_temp": 119.9, "cyl_4_temp": 120.0,
    "oil_pressure": 4.5,
    "rpm": 5250.0,
    "egt_1_temp": 449.0, "egt_2_temp": 320.0, "egt_3_temp": 448.0, "egt_4_temp": 451.0,
    "vibration_rms": 1.1,
    "fuel_flow_1": 10.0, "fuel_flow_2": 10.0, "fuel_flow_3": 10.0, "fuel_flow_4": 10.0,
    "oil_temp": 96.0,
}

result = run_inference(test_frame)
print(result["primary_root_cause"])