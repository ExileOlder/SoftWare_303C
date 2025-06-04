"""
WSGI config for hotel_ac project.
"""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'hotel_ac.settings')

application = get_wsgi_application() 