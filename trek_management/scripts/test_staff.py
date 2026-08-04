import os
import unittest
from flask import session
from app.database import Base, engine, SessionLocal
from main import create_app
from app.models import User, StaffProfile, Trek, Booking, TrekStaffAssignment, UserRole, ApprovalStatus, TrekStatus, Difficulty
from app.security import hash_password
from datetime import datetime, timezone, timedelta

class StaffDashboardTestCase(unittest.TestCase):
    def setUp(self):
        # Create app and test client
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.app.config['WTF_CSRF_ENABLED'] = False
        self.client = self.app.test_client()
        
        # Test db session
        self.db = SessionLocal()

    def tearDown(self):
        self.db.close()

    def test_01_staff_login(self):
        # The user was created by seed_data: jane.guide@example.com / GuidePass1!
        response = self.client.post('/login', data=dict(
            email='jane.guide@example.com',
            password='GuidePass1!'
        ), follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Trek Staff', response.data)
        
    def test_02_staff_dashboard(self):
        with self.client as c:
            c.post('/login', data=dict(email='jane.guide@example.com', password='GuidePass1!'))
            response = c.get('/staff/dashboard')
            self.assertEqual(response.status_code, 200)
            self.assertIn(b'Assigned Treks', response.data)
            self.assertIn(b'Registered Trekkers', response.data)
            
    def test_03_my_treks(self):
        with self.client as c:
            c.post('/login', data=dict(email='jane.guide@example.com', password='GuidePass1!'))
            response = c.get('/staff/treks')
            self.assertEqual(response.status_code, 200)
            self.assertIn(b'Hampta Pass', response.data)
            self.assertNotIn(b'Everest Base Camp', response.data) # Unassigned trek
            
    def test_04_unauthorized_trek_access(self):
        with self.client as c:
            c.post('/login', data=dict(email='jane.guide@example.com', password='GuidePass1!'))
            # ID 2 is Everest Base Camp (unassigned)
            response = c.get('/staff/treks/2', follow_redirects=True)
            self.assertEqual(response.status_code, 200)
            self.assertIn(b'You are not authorized to access this trek', response.data)

    def test_05_update_slots_down(self):
        # Update slots to 17
        with self.client as c:
            c.post('/login', data=dict(email='jane.guide@example.com', password='GuidePass1!'))
            response = c.post('/staff/treks/1/update-slots', data=dict(
                available_slots='17'
            ), follow_redirects=True)
            self.assertIn(b'Available slots updated to 17', response.data)

            # verify in DB
            trek = self.db.query(Trek).filter(Trek.id == 1).first()
            self.assertEqual(trek.available_slots, 17)
            
    def test_06_update_status(self):
        with self.client as c:
            c.post('/login', data=dict(email='jane.guide@example.com', password='GuidePass1!'))
            response = c.post('/staff/treks/1/update-status', data=dict(
                status='Active'
            ), follow_redirects=True)
            self.assertIn(b'Trek status updated', response.data)
            
            trek = self.db.query(Trek).filter(Trek.id == 1).first()
            self.assertEqual(trek.status, TrekStatus.ACTIVE)

if __name__ == '__main__':
    unittest.main()
