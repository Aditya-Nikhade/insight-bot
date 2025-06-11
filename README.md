# Insight Bot

A Python-based bot application for generating insights and analysis.

## Features

- Web interface for interaction
- Docker containerization support
- Command processing functionality
- Template-based response generation

## Setup

1. Clone the repository
2. Create a virtual environment:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```
3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

## Running the Application

### Using Docker
```bash
docker build -t insight-bot .
docker run -p 5000:5000 insight-bot
```

### Without Docker
```bash
python app.py
```

## Project Structure

- `app.py` - Main application file
- `templates/` - HTML templates
- `Dockerfile` - Docker configuration
- `requirements.txt` - Project dependencies

## Requirements

See `requirements.txt` for the complete list of dependencies.
