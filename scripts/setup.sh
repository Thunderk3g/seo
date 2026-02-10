#!/bin/bash

# Setup script for Multi-Agent AI Backend

echo "Initializing environment..."

# Check for python
if ! command -v python3 &> /dev/null
then
    echo "Python could not be found. Please install Python 3.10+"
    exit
fi

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install --upgrade pip
pip install -e .

# Create .env from template if it doesn't exist
if [ ! -f .env ]; then
    cp .env.example .env
    echo ".env file created from .env.example. Please update your API keys."
fi

echo "Setup complete. Run 'uvicorn app.main:app --reload' to start."
