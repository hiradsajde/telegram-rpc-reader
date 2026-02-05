# Project Setup Guide

## Development Environment

### Prerequisites
Before starting the project, you need to set up a Python virtual environment:

1. Create and activate the virtual environment:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

### Running the Development Server

To start the development server, run:

```bash
sh run.sh
```

This method is recommended for development purposes.

## Production Deployment

For production launch, use Docker Compose:

```bash
docker compose up
```

This will build and start all necessary containers for the production environment.