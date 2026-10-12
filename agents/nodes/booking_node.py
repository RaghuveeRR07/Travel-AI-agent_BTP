import os
import subprocess
import sys
import tempfile
from pathlib import Path

from models.booking import BookingRecord, PaymentRequest, PaymentResult
from models.trip import TripRequest
from ui.console import console, print_booking_confirmed


def simulate_booking_node(state: dict) -> dict:
    idx = state["current_booking_index"]
    selected = state["search_results"].get(f"{idx}_selected", {})
    item = state["bookable_items"][idx]
    trip = TripRequest(**state["trip_request"])

    provider = selected.get("name") or selected.get("airline") or "Provider"
    amount = selected.get("total_price_usd") or selected.get("price_usd") or 0.0

    payment_req = PaymentRequest(
        booking_type=item["type"],
        provider_name=provider,
        amount=float(amount),
        currency=trip.preferred_currency,
        traveler_names=[f"Traveler {i + 1}" for i in range(trip.num_travelers)],
        booking_reference=f"BTP-{idx}",
        simulate=True,
    )

    gateway_path = Path(__file__).resolve().parent.parent.parent / "services" / "payment_gateway.py"

    # Write PaymentRequest to a temp file so stdin stays open as a TTY,
    # allowing getpass() in the subprocess to read from /dev/tty directly.
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        f.write(payment_req.model_dump_json())
        tmp_path = f.name

    console.print(f"\n[dim]Launching secure payment gateway for {provider}...[/dim]")

    try:
        proc = subprocess.run(
            [sys.executable, str(gateway_path), tmp_path],
            stdout=subprocess.PIPE,
            text=True,
            timeout=120,
        )
    finally:
        os.unlink(tmp_path)

    if proc.returncode != 0:
        return {"error_message": f"Payment gateway exited with error (code {proc.returncode})."}

    result = PaymentResult.model_validate_json(proc.stdout.strip())

    record = BookingRecord(
        item_type=item["type"],
        confirmation_number=result.confirmation_id,
        details=selected,
        status=result.status,
    )
    print_booking_confirmed(record)
    return {"booking_records": list(state["booking_records"]) + [record.model_dump()]}
