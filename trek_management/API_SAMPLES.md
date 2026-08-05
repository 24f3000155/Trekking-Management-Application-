# API Integration Guide

This document provides sample cURL requests for the Trek Management System API.

## Authentication

The API uses **Session-based Authentication**. When calling APIs from browser-based applications (like the Dashboard via AJAX), cookies are passed automatically. 
For external clients, you must first authenticate via the login endpoint to receive a session cookie.

---

## 1. Treks API

### List Treks (GET)
Returns a paginated list of treks.

```bash
curl -X GET "http://localhost:5000/api/treks?page=1&per_page=10&status=Open" \
     -b cookies.txt
```

### Get Trek Details (GET)
```bash
curl -X GET "http://localhost:5000/api/treks/1" \
     -b cookies.txt
```

### Create a Trek (POST, Admin Only)
```bash
curl -X POST "http://localhost:5000/api/treks" \
     -H "Content-Type: application/json" \
     -b cookies.txt \
     -d '{
           "trek_name": "API created Trek",
           "location": "Himalayas",
           "description": "Created via API",
           "difficulty": "Hard",
           "duration_days": 10,
           "total_slots": 20,
           "price": 5000.00,
           "start_date": "2026-10-01",
           "end_date": "2026-10-10",
           "status": "Pending"
         }'
```

### Update a Trek (PUT, Admin Only)
```bash
curl -X PUT "http://localhost:5000/api/treks/1" \
     -H "Content-Type: application/json" \
     -b cookies.txt \
     -d '{
           "status": "Approved",
           "price": 5500.00
         }'
```

### Delete a Trek (DELETE, Admin Only)
```bash
curl -X DELETE "http://localhost:5000/api/treks/1" \
     -b cookies.txt
```

---

## 2. Bookings API

### List Bookings (GET)
Users see their own bookings. Admins see all bookings.
```bash
curl -X GET "http://localhost:5000/api/bookings" \
     -b cookies.txt
```

### Get Booking Details (GET)
```bash
curl -X GET "http://localhost:5000/api/bookings/1" \
     -b cookies.txt
```

### Create a Booking (POST, Trekker Only)
```bash
curl -X POST "http://localhost:5000/api/bookings" \
     -H "Content-Type: application/json" \
     -b cookies.txt \
     -d '{
           "trek_id": 1,
           "participants": 2
         }'
```

### Update Booking Status (PUT, Admin/Staff Only)
Valid actions: `cancel`, `complete`.
```bash
curl -X PUT "http://localhost:5000/api/bookings/1" \
     -H "Content-Type: application/json" \
     -b cookies.txt \
     -d '{"action": "complete"}'
```

### Cancel Booking (DELETE, Admin or Owner)
```bash
curl -X DELETE "http://localhost:5000/api/bookings/1" \
     -b cookies.txt
```

---

## 3. Users API

### List Users (GET, Admin Only)
```bash
curl -X GET "http://localhost:5000/api/users" \
     -b cookies.txt
```

### Get User Profile (GET)
```bash
curl -X GET "http://localhost:5000/api/users/1" \
     -b cookies.txt
```

### Create User (POST, Admin Only)
```bash
curl -X POST "http://localhost:5000/api/users" \
     -H "Content-Type: application/json" \
     -b cookies.txt \
     -d '{
           "name": "API User",
           "email": "apiuser@example.com",
           "password": "StrongPassword123",
           "role": "Trekker"
         }'
```

### Update User (PUT)
```bash
curl -X PUT "http://localhost:5000/api/users/1" \
     -H "Content-Type: application/json" \
     -b cookies.txt \
     -d '{
           "name": "Updated Name",
           "phone": "9876543210"
         }'
```

### Deactivate User (DELETE, Admin Only)
```bash
curl -X DELETE "http://localhost:5000/api/users/1" \
     -b cookies.txt
```

---

## Error Handling

Standard error format returned on failure (e.g., 422 Unprocessable Entity):
```json
{
  "success": false,
  "message": "Validation failed",
  "errors": {
    "email": "Invalid email format",
    "password": "Password must be at least 6 characters"
  }
}
```
