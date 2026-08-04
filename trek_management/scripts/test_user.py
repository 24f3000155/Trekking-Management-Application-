import os
import unittest
from flask import session
from app.database import SessionLocal, Base, engine
from main import create_app
from app.models import User, Trek, Booking, UserRole, TrekStatus, Difficulty
from datetime import datetime, timezone, timedelta

class UserDashboardTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # We can optionally drop/create or just use test user
        pass

    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.app.config['WTF_CSRF_ENABLED'] = False
        self.client = self.app.test_client()
        self.db = SessionLocal()

        # Generate a test user email logic to avoid duplicates
        self.test_email = 'testuser.booking@example.com'
        
        # Make sure user does not exist
        u = self.db.query(User).filter_by(email=self.test_email).first()
        if u:
            self.db.delete(u)
            self.db.commit()

    def tearDown(self):
        # Clean up
        u = self.db.query(User).filter_by(email=self.test_email).first()
        if u:
            self.db.delete(u)
            self.db.commit()
        self.db.close()

    def test_01_user_registration(self):
        response = self.client.post('/register', data=dict(
            name='Test Trekker',
            email=self.test_email,
            phone='1234567890',
            password='Password1!',
            confirm_password='Password1!'
        ), follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Registration successful', response.data)

        # Check DB
        u = self.db.query(User).filter_by(email=self.test_email).first()
        self.assertIsNotNone(u)
        self.assertEqual(u.role, UserRole.TREKKER)

    def test_02_user_login(self):
        # Must register first
        self.test_01_user_registration()
        
        response = self.client.post('/login', data=dict(
            email=self.test_email,
            password='Password1!'
        ), follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Dashboard', response.data)
        
    def test_03_duplicate_booking_prevention(self):
        self.test_01_user_registration()
        
        with self.client as c:
            c.post('/login', data=dict(email=self.test_email, password='Password1!'))
            
            # Find an open trek
            trek = self.db.query(Trek).filter(Trek.status == TrekStatus.UPCOMING, Trek.available_slots > 0).first()
            if not trek:
                self.skipTest("No available treks to test booking.")
            
            # First booking
            response1 = c.post(f'/user/treks/{trek.id}/book', data=dict(participants=1), follow_redirects=True)
            self.assertIn(b'Booking confirmed!', response1.data)
            
            # Second booking on the same trek
            response2 = c.post(f'/user/treks/{trek.id}/book', data=dict(participants=1), follow_redirects=True)
            self.assertIn(b'You already have an active booking for this trek.', response2.data)
            
            # Cancel the booking to clean up slot
            booking = self.db.query(Booking).filter_by(trek_id=trek.id).join(User).filter(User.email == self.test_email).first()
            if booking:
                c.post(f'/user/bookings/{booking.id}/cancel')

if __name__ == '__main__':
    unittest.main()
