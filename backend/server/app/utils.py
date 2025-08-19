from .alerts import send_alert

def maybe_alert(device, m):
    alerts = []
    if m.cpu >= 95: alerts.append(f"CPU {m.cpu:.0f}%")
    if m.mem >= 95: alerts.append(f"MEM {m.mem:.0f}%")
    if m.disk >= 95: alerts.append(f"DISK {m.disk:.0f}%")
    if m.battery_pct is not None and m.battery_pct <= 10: alerts.append(f"Battery {m.battery_pct:.0f}%")
    if alerts:
        send_alert(f"⚠️ {device.hostname} threshold", ", ".join(alerts))
