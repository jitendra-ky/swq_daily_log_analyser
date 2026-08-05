#!/usr/bin/env bash
# Exit on error
set -o errexit

# Export dependencies from uv to a standard requirements.txt
uv export --format requirements-txt > requirements.txt

# Install dependencies using standard pip
pip install -U pip
pip install -r requirements.txt

# Collect static files
python manage.py collectstatic --no-input

# Run migrations
python manage.py migrate
