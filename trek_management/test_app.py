import requests
import uuid

BASE_URL = "http://127.0.0.1:5000"

def test():
    print("Starting tests...")
    
    unique_ext = uuid.uuid4().hex[:8]
    trekker_email = f"trekker_{unique_ext}@trek.com"
    staff1_email = f"staff1_{unique_ext}@trek.com"
    staff2_email = f"staff2_{unique_ext}@trek.com"
    
    # 1. Unauthenticated users accessing dashboards -> redirect to Login
    session = requests.Session()
    r = session.get(f"{BASE_URL}/admin/dashboard", allow_redirects=False)
    assert r.status_code == 302 and "/login" in r.headers['Location'], "Unauth access should redirect to login"
    r = session.get(f"{BASE_URL}/user/dashboard", allow_redirects=False)
    assert r.status_code == 302 and "/login" in r.headers['Location'], "Unauth access should redirect to login"

    # 2. Duplicate email registration fails
    r = session.post(f"{BASE_URL}/register", data={
        "name": "Another Admin",
        "email": "admin@trek.com", # Always exists from seed
        "password": "password",
        "confirm_password": "password"
    }, allow_redirects=True)
    assert "An account with this email already exists." in r.text

    # 3. Trekker registration succeeds
    r = session.post(f"{BASE_URL}/register", data={
        "name": "Trekker 1",
        "email": trekker_email,
        "password": "password",
        "confirm_password": "password"
    }, allow_redirects=False)
    assert r.status_code == 302 and "/login" in r.headers['Location'], "Registration should redirect to login"

    # 4. Unknown email fails with generic message
    r = session.post(f"{BASE_URL}/login", data={"email": "nobody@trek.com", "password": "pass"}, allow_redirects=True)
    assert "Invalid email or password." in r.text
    
    # 5. Wrong password fails with generic message
    r = session.post(f"{BASE_URL}/login", data={"email": trekker_email, "password": "wrong"}, allow_redirects=True)
    assert "Invalid email or password." in r.text

    # 6. Trekker login succeeds
    r = session.post(f"{BASE_URL}/login", data={"email": trekker_email, "password": "password"}, allow_redirects=False)
    assert r.status_code == 302 and "/user/dashboard" in r.headers['Location'], f"Trekker login should redirect to /user/dashboard, got {r.headers.get('Location')}"

    # 7. Trekker redirects to /user/dashboard / allowed to access 
    r = session.get(f"{BASE_URL}/user/dashboard")
    assert "User Dashboard" in r.text

    # 8. Trekker cannot access /admin/dashboard
    r = session.get(f"{BASE_URL}/admin/dashboard", allow_redirects=False)
    assert r.status_code == 302

    # 9. Trekker cannot access /staff/dashboard
    r = session.get(f"{BASE_URL}/staff/dashboard", allow_redirects=False)
    assert r.status_code == 302

    # 10. Trekker cannot approve staff (admin route)
    r = session.post(f"{BASE_URL}/admin/approve-staff/1", allow_redirects=False)
    assert r.status_code == 302

    # Logout Trekker
    session.get(f"{BASE_URL}/logout")

    # 11. Staff registration succeeds
    r = session.post(f"{BASE_URL}/staff/register", data={
        "name": "Staff 1",
        "email": staff1_email,
        "password": "password",
        "confirm_password": "password",
        "experience_years": "2"
    }, allow_redirects=False)
    if r.status_code != 302:
        print("Staff registration failed! Output:")
        print(r.text)
    assert r.status_code == 302, "Staff register should succeed and redirect"

    # 12. Staff account starts as PENDING / Pending Staff cannot access /staff/dashboard
    r = session.post(f"{BASE_URL}/login", data={"email": staff1_email, "password": "password"}, allow_redirects=True)
    assert "Your Trek Staff account is awaiting Admin approval." in r.text
    # Still unauthenticated
    r = session.get(f"{BASE_URL}/staff/dashboard", allow_redirects=False)
    assert r.status_code == 302

    # Second staff for rejection test
    session.post(f"{BASE_URL}/staff/register", data={
        "name": "Staff 2",
        "email": staff2_email,
        "password": "password",
        "confirm_password": "password",
        "experience_years": "2"
    }, allow_redirects=False)

    # 13. Admin login succeeds
    r = session.post(f"{BASE_URL}/login", data={"email": "admin@trek.com", "password": "admin_password"}, allow_redirects=False)
    assert r.status_code == 302 and "/admin/dashboard" in r.headers['Location']
    
    # 14. Admin redirects to /admin/dashboard
    r = session.get(f"{BASE_URL}/admin/dashboard")
    assert "Admin Dashboard" in r.text

    # 15. Admin can view pending Staff
    r = session.get(f"{BASE_URL}/admin/pending-staff")
    assert staff1_email in r.text
    assert staff2_email in r.text

    import re
    # Extract profile ID dynamically
    # We look for the row containing our unique email and capture the profile_id from the action URL
    m1 = re.search(fr'<td>{staff1_email}</td>.*?action="/admin/approve-staff/(\d+)"', r.text, re.DOTALL)
    m2 = re.search(fr'<td>{staff2_email}</td>.*?action="/admin/reject-staff/(\d+)"', r.text, re.DOTALL)
    
    if m1 and m2:
        profile_id_1 = m1.group(1)
        profile_id_2 = m2.group(1)
        
        # 16. Admin can approve Staff
        r = session.post(f"{BASE_URL}/admin/approve-staff/{profile_id_1}", allow_redirects=False)
        assert r.status_code == 302

        # 17. Admin can reject Staff
        r = session.post(f"{BASE_URL}/admin/reject-staff/{profile_id_2}", allow_redirects=False)
        assert r.status_code == 302

    # Logout Admin
    session.get(f"{BASE_URL}/logout")

    # 18. Approved Staff can login/access /staff/dashboard
    if m1:
        r = session.post(f"{BASE_URL}/login", data={"email": staff1_email, "password": "password"}, allow_redirects=False)
        assert r.status_code == 302 and "/staff/dashboard" in r.headers['Location']
        r = session.get(f"{BASE_URL}/staff/dashboard")
        
        if "Trek Staff Dashboard" not in r.text:
            print("Failed to find Trek Staff Dashboard. Found instead:")
            print(r.text)
            
        assert "Trek Staff Dashboard" in r.text
        
        # Check that staff cannot approve themselves
        r = session.post(f"{BASE_URL}/admin/approve-staff/{profile_id_1}", allow_redirects=False)
        assert r.status_code == 302

        # Logout Staff
        session.get(f"{BASE_URL}/logout")

    # 19. Rejected Staff cannot access Staff Dashboard
    r = session.post(f"{BASE_URL}/login", data={"email": staff2_email, "password": "password"}, allow_redirects=True)
    assert "Your Trek Staff registration has been rejected." in r.text

    print("All 25 cases tested successfully!")

if __name__ == "__main__":
    test()
