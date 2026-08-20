# AuraStock Enterprise - Multi-Warehouse Inventory Management System

A high-performance, production-grade inventory management system designed for multi-warehouse distribution networks. Featuring an **immutable double-entry stock ledger**, fine-grained **RBAC permissions**, unified **React Web & Tauri Windows Desktop clients**, **FastAPI asynchronous backend**, **PostgreSQL/SQLite** persistence, **hardware barcode scanning & direct thermal label printing**, and **offline-first edge synchronization preparedness**.

---

## Key Features

1. **Immutable Double-Entry Stock Ledger**:
   - Every stock movement (receipt, putaway, pick, transfer, scrap, count adjustment) creates a balanced journal transaction with debit and credit balance locations.
   - Row-level locking prevents race conditions and balance drift.
   - Dual valuation support: **FIFO (First-In, First-Out)** and **Moving Weighted Average**.
2. **Unified Frontend (Web & Tauri Windows Desktop)**:
   - Shared React 18/19 SPA with custom Slate & Deep Indigo enterprise design tokens.
   - Web Audio API synthesizer for instant audio feedback upon scanning.
   - Cross-platform Native Bridge for USB Keyboard Wedge, Tauri Serial COM port barcode scanners, and direct ESC/POS / Zebra ZPL printing.
3. **Multi-Warehouse & Bin Hierarchy**:
   - Aisle, Rack, Shelf, and Bin zone management (Storage, Inbound Receiving, Outbound Staging, Shipping, Quarantine).
4. **End-to-End Workflows**:
   - **Procurement**: Purchase Orders, multi-step approval workflows, and Goods Receipt (GRN) posting directly to the stock ledger.
   - **Sales & Fulfillment**: Sales Orders, stock allocation/reservation, and dispatch shipping issue postings.
   - **Barcode Station**: Code128 and 2D QR Code generator with printable thermal label templates.
   - **Compliance & Audit Trails**: Cryptographic audit logging with JSON state mutation diffs.
   - **Valuation & Analytics**: Real-time asset reports with CSV exports.

---

## Repository Monorepo Structure

```
inventory-management-system/
├── apps/
│   ├── web/                  # React 18+ Single Page App (Vite + TypeScript)
│   ├── desktop-tauri/        # Tauri v2 Windows Desktop Shell (Rust backend)
│   └── backend/              # FastAPI Python Async Application
├── packages/
│   ├── shared-types/         # Shared TypeScript contracts & models
│   └── native-bridge/        # Hardware Bridge (Web HID vs Tauri Serial/Spooler)
├── deploy/                   # Dockerfiles, Nginx config & Docker Compose
└── pytest.ini                # Pytest configuration
```

---

## Quickstart & Local Execution

### 1. Backend Server (FastAPI)
```bash
# Install Python dependencies
pip install -r apps/backend/requirements.txt

# Start backend dev server (Auto-initializes DB schema and seeds rich demo data)
python -m uvicorn app.main:app --app-dir apps/backend --reload --port 8000
```
- Interactive Swagger API Documentation: [http://localhost:8000/api/v1/docs](http://localhost:8000/api/v1/docs)
- Interactive ReDoc: [http://localhost:8000/api/v1/redoc](http://localhost:8000/api/v1/redoc)
- Health Check: [http://localhost:8000/health](http://localhost:8000/health)

### 2. Frontend Web Application (React)
```bash
# Install Node dependencies
npm install

# Start Vite Development Server
npm --prefix apps/web run dev
```
- Access Web Dashboard: [http://localhost:5173](http://localhost:5173)

---

## Seed Demo Credentials

The database initializes automatically with pre-configured operational roles and accounts:

| Role | Email | Password | Scope & Permissions |
| :--- | :--- | :--- | :--- |
| **Super Admin** | `admin@inventory.local` | `Admin123!` | Full unrestricted access to all modules, users & ledger |
| **Austin WH Manager** | `manager@inventory.local` | `Manager123!` | Manages warehouses, PO approvals, stock transfers & reports |
| **Inventory Clerk** | `clerk@inventory.local` | `Clerk123!` | Scans barcodes, records receipts, transfers & count adjustments |

---

## Running Test Suites

Run the comprehensive asynchronous backend test suite verifying RBAC authentication, double-entry stock ledger calculations, concurrency row-locking, and reporting:

```bash
python -m pytest -v
```

To build and validate the React production bundle:
```bash
npm --prefix apps/web run build
```

---

## Docker Production Deployment

Deploy the entire high-availability cluster (FastAPI + PostgreSQL 16 + Redis 7 + Nginx Ingress) using Docker Compose:

```bash
docker-compose -f deploy/docker-compose.yml up -d --build
```
- Web Application & Reverse Proxy: [http://localhost](http://localhost)
- Backend REST API: [http://localhost/api/v1](http://localhost/api/v1)

---

## License & Architecture
Designed and engineered for enterprise inventory environments. MIT Licensed.
