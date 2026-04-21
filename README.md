# Argus Omega // Beastmode Intelligence Engine

Argus Omega is an institutional-grade fusion layer designed to adjudicate and synthesize market intelligence from four specialized subsystems into a single, high-conviction decision-support output.

## Subsystems
- **ARGUS**: Live hidden-state intelligence (bias, stability, expansion risk).
- **ECHO FORGE**: Historical analog and recurrence engine (similarity, continuation edge).
- **LIQUIDITY GHOST**: Liquidity destination and sweep mapping (destination score, magnets).
- **FALSE REALITY**: Deception and trap detection engine (truth score, trap probability).

## Core Logic
The engine uses a sophisticated adjudication model that:
1.  **Normalizes** all subsystem inputs into a common semantic frame.
2.  **Infers Direction** for each subsystem.
3.  **Computes Alignment** using weighted directional votes, with specific adjudication rules for conflict.
4.  **Applies Penalties & Bonuses** for deception, contradiction, and alignment quality.
5.  **Calculates Omega Score & Conviction** based on synchronized subsystem confidence.
6.  **Ranks Scenarios** using probabilistic softmax logits.
7.  **Maps Action Classes** to disciplined postures (e.g., `watch_for_sweep`, `do_not_chase`).

## Tech Stack
- **API**: FastAPI (Python 3.11+)
- **Validation**: Pydantic V2 (strict Literal enforcement)
- **Containerization**: Docker & Docker Compose
- **Testing**: Pytest (Mathematical Parity Suite)

## Getting Started

### Prerequisites
- Python 3.11+ or Docker

### Installation
1. Clone the repository.
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Create a `.env` file from `.env.example`:
   ```bash
   cp .env.example .env
   ```

### Running the Service
```bash
# Using Python
$env:PYTHONPATH="."; uvicorn app.main:app --reload --port 8080

# Using Docker
docker-compose up --build
```

### API Documentation
Once running, visit:
- Swagger UI: `http://localhost:8080/docs`
- Redoc: `http://localhost:8080/redoc`

## Testing
To verify mathematical parity with the reference implementation:
```bash
$env:PYTHONPATH="."; pytest TESTS/test_parity.py
```

## Security & Guardrails
- **No Simple Averages**: The adjudication layer uses institutional logic to handle signal contradictions.
- **Deception Suppression**: High deception scores from False Reality heavily penalize conviction and omega score.
- **Strict Validation**: All inputs are validated for range (0.0-1.0 or 0.0-100.0) and valid institutional states.
