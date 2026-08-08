"""Final Verification Script for RISE HIGH"""
import requests
import re

s = requests.Session()
base = 'http://127.0.0.1:5000'

print('='*60)
print('RISE HIGH - FINAL VERIFICATION')
print('='*60)

# 1. Login page
print('\n[1] Login page...')
r = s.get(f'{base}/login')
print(f'  Status: {r.status_code}')
has_old_brand = 'Trek Management System' in r.text or 'Trek Admin' in r.text or 'Trek Explorer' in r.text
print(f'  Old branding found: {has_old_brand}')
has_rise_high = 'RISE HIGH' in r.text
print(f'  RISE HIGH branding: {has_rise_high}')
has_image1 = 'Image1.png' in r.text
print(f'  Image1 reference: {has_image1}')
has_logo = 'Image2.png' in r.text
print(f'  Logo (Image2) on login: {has_logo} (should be False)')

# 2. Admin login + dashboard
print('\n[2] Admin login...')
csrf = re.search(r'name="csrf_token" value="([^"]+)"', r.text)
token = csrf.group(1) if csrf else ''
r = s.post(f'{base}/login', data={'email':'admin@example.com','password':'AdminPass1!','csrf_token':token}, allow_redirects=True)
print(f'  Status: {r.status_code}, URL: {r.url}')
print(f'  Landed on admin dashboard: {"admin" in r.url}')
has_admin_css = 'admin.css' in r.text
print(f'  admin.css loaded: {has_admin_css}')
has_old_brand_admin = 'Trek Management System' in r.text
print(f'  Old branding in admin: {has_old_brand_admin}')

# 3. Admin routes
admin_routes = ['/admin/treks', '/admin/staff', '/admin/users', '/admin/bookings', '/admin/assignments', '/admin/trek-history', '/admin/booking-history', '/admin/search']
print('\n[3] Admin routes:')
for route in admin_routes:
    r = s.get(f'{base}{route}')
    status = 'OK' if r.status_code == 200 else f'FAIL ({r.status_code})'
    print(f'  {route}: {status}')

# 4. Admin logout
print('\n[4] Admin logout...')
r = s.get(f'{base}/logout', allow_redirects=True)
print(f'  Status: {r.status_code}, back at login: {"login" in r.url}')

# 5. Trekker login
print('\n[5] Trekker login...')
r = s.get(f'{base}/login')
csrf = re.search(r'name="csrf_token" value="([^"]+)"', r.text)
token = csrf.group(1) if csrf else ''
r = s.post(f'{base}/login', data={'email':'john.trekker@example.com','password':'TrekkerPass1!','csrf_token':token}, allow_redirects=True)
print(f'  Status: {r.status_code}, URL: {r.url}')
print(f'  Landed on user dashboard: {"user" in r.url}')
has_user_css = 'user.css' in r.text
print(f'  user.css loaded: {has_user_css}')

# 6. Trekker routes
user_routes = ['/user/dashboard', '/user/treks', '/user/bookings', '/user/history', '/user/profile']
print('\n[6] Trekker routes:')
for route in user_routes:
    r = s.get(f'{base}{route}')
    status = 'OK' if r.status_code == 200 else f'FAIL ({r.status_code})'
    print(f'  {route}: {status}')

# 7. Trekker logout
r = s.get(f'{base}/logout', allow_redirects=True)
print(f'\n[7] Trekker logout: back at login: {"login" in r.url}')

# 8. Staff login
print('\n[8] Staff login...')
r = s.get(f'{base}/login')
csrf = re.search(r'name="csrf_token" value="([^"]+)"', r.text)
token = csrf.group(1) if csrf else ''
r = s.post(f'{base}/login', data={'email':'jane.guide@example.com','password':'GuidePass1!','csrf_token':token}, allow_redirects=True)
print(f'  Status: {r.status_code}, URL: {r.url}')
print(f'  Landed on staff dashboard: {"staff" in r.url}')
has_staff_css = 'staff.css' in r.text
print(f'  staff.css loaded: {has_staff_css}')

# 9. Staff routes
staff_routes = ['/staff/dashboard', '/staff/treks', '/staff/participants', '/staff/trek-history', '/staff/profile']
print('\n[9] Staff routes:')
for route in staff_routes:
    r = s.get(f'{base}{route}')
    status = 'OK' if r.status_code == 200 else f'FAIL ({r.status_code})'
    print(f'  {route}: {status}')

# 10. Staff logout
r = s.get(f'{base}/logout', allow_redirects=True)
print(f'\n[10] Staff logout: back at login: {"login" in r.url}')

# 11. RBAC
print('\n[11] RBAC verification (anon access blocked)...')
r = s.get(f'{base}/admin/dashboard', allow_redirects=True)
print(f'  Anon -> /admin/dashboard: {"login" in r.url} (should be True)')
r = s.get(f'{base}/staff/dashboard', allow_redirects=True)
print(f'  Anon -> /staff/dashboard: {"login" in r.url} (should be True)')
r = s.get(f'{base}/user/dashboard', allow_redirects=True)
print(f'  Anon -> /user/dashboard: {"login" in r.url} (should be True)')

# 12. Register page check
print('\n[12] Register page...')
r = s.get(f'{base}/register')
print(f'  Status: {r.status_code}')
has_old = 'Trek Management' in r.text
print(f'  Old branding: {has_old}')

# 13. Staff register page
print('\n[13] Staff register page...')
r = s.get(f'{base}/staff/register')
print(f'  Status: {r.status_code}')
has_old = 'Trek Management' in r.text
print(f'  Old branding: {has_old}')

print('\n' + '='*60)
print('VERIFICATION COMPLETE')
print('='*60)
