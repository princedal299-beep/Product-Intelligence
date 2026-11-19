import logging
import random
import string
import uuid
from locust import HttpUser, task, between

# Configure local logger for clear test execution output in console
logger = logging.getLogger("locust.security_test")


def generate_random_email() -> str:
    r"""
    Generate a random, non-existent email address for unauthorized login testing.
    Uses RFC 2606 reserved '.invalid' domain to guarantee no real email is contacted.
    Matches the backend email validation regex: [^@\s]+@[^@\s]+\.[^@\s]+
    """
    random_id = uuid.uuid4().hex[:8]
    return f"fake_admin_{random_id}@example.invalid"


def generate_random_password(length: int = 12) -> str:
    """
    Generate a random password with uppercase, lowercase, numbers, and symbols.
    Ensures that test attempts use incorrect, non-existent credentials.
    """
    chars = string.ascii_letters + string.digits + "!@#$%^&*"
    return "".join(random.choice(chars) for _ in range(length))


class FastAPIUser(HttpUser):
    """
    Locust user class simulating unauthorized users attempting to access
    the admin panel and protected API endpoints.
    """
    # Keep the user's required wait time between 1 and 2 seconds
    wait_time = between(1, 2)

    @task(1)
    def test_login_page_probe(self):
        """
        Probe the /Login endpoint with GET to verify endpoint behavior.
        
        NOTE: In this FastAPI application, /Login is registered as a POST-only API
        endpoint for OAuth2 authentication. FastAPI returns 405 Method Not Allowed
        when accessed via GET. If this script is run against a frontend web proxy
        that serves an HTML login page, it will return 200 OK.
        """
        with self.client.get("/Login", catch_response=True, name="[Probe] GET /Login") as response:
            if response.status_code == 200:
                response.success()
            elif response.status_code == 405:
                # 405 is expected for FastAPI because /Login only accepts POST
                response.success()
            elif response.status_code == 429:
                # Rate limit triggered by RateLimitMiddleware (20 req/min)
                response.success()
            else:
                response.failure(
                    f"Unexpected status code for GET /Login: {response.status_code}"
                )

    @task(4)
    def test_unauthorized_login(self):
        """
        Simulate an unauthorized user attempting to log into the Admin panel.
        
        Key Backend Findings:
        - Route: POST /Login (or POST /login)
        - Format: application/x-www-form-urlencoded (FastAPI OAuth2PasswordRequestForm)
        - Payload fields: 'username' and 'password' (passed via data={...})
        - Expected Response: 401 Unauthorized for invalid credentials
        - Rate Limit: 429 Too Many Requests if exceeding 20 requests/minute
        """
        fake_email = generate_random_email()
        fake_password = generate_random_password()

        # FastAPI OAuth2 expects form data (data=...), NOT JSON (json=...)
        payload = {
            "username": fake_email,
            "password": fake_password,
        }

        with self.client.post(
            "/Login",
            data=payload,
            catch_response=True,
            name="[Auth] POST /Login - Unauthorized Attempt",
        ) as response:
            if response.status_code == 401:
                # Expected: Backend correctly rejected the unauthorized credentials
                response.success()
            elif response.status_code == 429:
                # Expected: RateLimitMiddleware triggered (20 requests/minute limit)
                retry_after = response.headers.get("Retry-After", "unknown")
                logger.info("Rate limit triggered (429). Retry-After: %s seconds", retry_after)
                response.success()
            elif response.status_code == 200:
                # Critical security flaw: Fake credentials were accepted!
                response.failure("SECURITY BREACH: Unauthorized login succeeded with 200 OK!")
            elif response.status_code == 422:
                # Validation error: Form data structure was not parsed correctly
                response.failure("Request payload format mismatch (422 Unprocessable Entity)")
            else:
                response.failure(
                    f"Unexpected status code on login: {response.status_code}"
                )

    @task(1)
    def test_admin_users_unauthenticated(self):
        """
        Attempt to access protected GET /admin/users without an Authorization header.
        Expected: 401 Unauthorized or 403 Forbidden.
        """
        with self.client.get(
            "/admin/users",
            params={"email": "nobody@example.invalid"},
            catch_response=True,
            name="[Admin] GET /admin/users - Unauthenticated",
        ) as response:
            if response.status_code in (401, 403):
                response.success()
            elif response.status_code == 429:
                response.success()
            elif response.status_code == 200:
                response.failure("SECURITY BREACH: Protected /admin/users accessible without auth!")
            else:
                response.failure(
                    f"Unexpected status on /admin/users: {response.status_code}"
                )

    @task(1)
    def test_admin_audit_unauthenticated(self):
        """
        Attempt to access protected GET /admin/audit without an Authorization header.
        Expected: 401 Unauthorized or 403 Forbidden.
        """
        with self.client.get(
            "/admin/audit",
            params={"limit": 10, "offset": 0},
            catch_response=True,
            name="[Admin] GET /admin/audit - Unauthenticated",
        ) as response:
            if response.status_code in (401, 403):
                response.success()
            elif response.status_code == 429:
                response.success()
            elif response.status_code == 200:
                response.failure("SECURITY BREACH: Protected /admin/audit accessible without auth!")
            else:
                response.failure(
                    f"Unexpected status on /admin/audit: {response.status_code}"
                )

    @task(1)
    def test_admin_reindex_unauthenticated(self):
        """
        Attempt to trigger POST /admin/reindex without an Authorization header.
        Expected: 401 Unauthorized or 403 Forbidden.
        """
        with self.client.post(
            "/admin/reindex",
            catch_response=True,
            name="[Admin] POST /admin/reindex - Unauthenticated",
        ) as response:
            if response.status_code in (401, 403):
                response.success()
            elif response.status_code == 429:
                response.success()
            elif response.status_code == 200:
                response.failure("SECURITY BREACH: Protected /admin/reindex triggered without auth!")
            else:
                response.failure(
                    f"Unexpected status on /admin/reindex: {response.status_code}"
                )
