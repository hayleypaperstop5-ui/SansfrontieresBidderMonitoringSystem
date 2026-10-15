from unittest.mock import patch

from django.test import Client, override_settings
from django.urls import reverse
from accounts.models import User

url = reverse("dashboard:process_payroll")

director = User.objects.filter(role=User.Role.DIRECTOR).first()
non_director = User.objects.exclude(role=User.Role.DIRECTOR).first()

print("DIRECTOR FOUND:", bool(director))
print("NON-DIRECTOR FOUND:", bool(non_director))

if not director or not non_director:
    raise SystemExit("REQUIRED TEST USERS NOT FOUND")

with override_settings(ALLOWED_HOSTS=["testserver"]):

    client = Client()

    # GET should redirect and must not process payroll.
    client.force_login(director)
    response = client.get(url)

    print("GET STATUS:", response.status_code)
    print("GET LOCATION:", response.get("Location"))

    # Non-Director POST should be denied.
    client.force_login(non_director)

    with patch("dashboard.views.process_thursday_payroll") as mocked_payroll:
        response = client.post(url)

    print("NON-DIRECTOR POST STATUS:", response.status_code)
    print("PAYROLL CALLED FOR NON-DIRECTOR:", mocked_payroll.called)

    # Director POST should call the service.
    # The service is mocked, so no real payment records are created.
    client.force_login(director)

    with patch(
        "dashboard.views.process_thursday_payroll",
        return_value={
            "payments_created": 0,
            "payment_ids": [],
        },
    ) as mocked_payroll:
        response = client.post(url)

    print("DIRECTOR POST STATUS:", response.status_code)
    print("DIRECTOR POST LOCATION:", response.get("Location"))
    print("PAYROLL CALLED FOR DIRECTOR:", mocked_payroll.called)

    if mocked_payroll.called:
        print("PAYROLL CALL KWARGS:", mocked_payroll.call_args.kwargs)

print("SAFE PAYROLL ENDPOINT TEST COMPLETE")
