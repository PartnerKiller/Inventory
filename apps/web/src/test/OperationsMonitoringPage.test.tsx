import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { OperationsMonitoringPage } from '../pages/OperationsMonitoringPage';
import { api } from '../api/client';

vi.mock('../api/client', () => ({
  api: {
    getOperationsStatus: vi.fn(),
    getOperationalMetrics: vi.fn(),
    getBackups: vi.fn(),
    triggerBackup: vi.fn(),
    runIntegrityCheck: vi.fn(),
  },
}));

describe('Phase 3D: Operations & Reliability Monitoring', () => {
  beforeEach(() => {
    vi.clearAllMocks();

    (api.getOperationsStatus as any).mockResolvedValue({
      status: 'OPERATIONAL',
      service: 'Enterprise Inventory Management System',
      version: '1.0.0',
      environment: 'production',
      database: {
        connected: true,
        latency_ms: 3.42,
        engine: 'PostgreSQL 16'
      },
      storage: {
        total_bytes: 100000000000,
        free_bytes: 65000000000,
        free_percent: 65.0
      },
      metrics_summary: {
        uptime_seconds: 86400,
        total_requests: 12500,
        error_count: 0,
        avg_latency_ms: 12.5,
        p95_latency_ms: 28.0
      },
      backup: {
        total_backups: 3,
        latest_backup: {
          filename: 'aurastock_pg_20260818_120000.sql.gz',
          size_bytes: 4500000,
          size_formatted: '4.29 MB',
          checksum_sha256: 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855',
          created_at: '2026-08-18T12:00:00Z',
          verified: true
        },
        retention_policy: '7 historical snapshots with SHA-256 verification'
      }
    });

    (api.getOperationalMetrics as any).mockResolvedValue({
      uptime_seconds: 86400,
      total_requests: 12500,
      status_breakdown: {
        '2xx': 12450,
        '3xx': 0,
        '4xx': 50,
        '5xx': 0
      },
      error_count: 0,
      latency_ms: {
        avg: 12.5,
        p95: 28.0,
        max: 85.0
      },
      last_backup: {
        timestamp: '2026-08-18T12:00:00Z',
        status: 'SUCCESS'
      },
      last_integrity_check: {
        timestamp: '2026-08-18T12:00:00Z',
        status: 'HEALTHY'
      }
    });

    (api.getBackups as any).mockResolvedValue([
      {
        filename: 'aurastock_pg_20260818_120000.sql.gz',
        size_bytes: 4500000,
        size_formatted: '4.29 MB',
        checksum_sha256: 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855',
        created_at: '2026-08-18T12:00:00Z',
        verified: true
      },
      {
        filename: 'aurastock_pg_20260817_120000.sql.gz',
        size_bytes: 4300000,
        size_formatted: '4.10 MB',
        checksum_sha256: 'ca978112ca1bbdcafac231b39a23dc4da786081419614b8a02b1f83a42d8f9d8',
        created_at: '2026-08-17T12:00:00Z',
        verified: true
      }
    ]);
  });

  it('renders OperationsMonitoringPage with executive KPIs and backup history', async () => {
    render(<OperationsMonitoringPage />);

    await waitFor(() => {
      expect(screen.getByText('System Operations & Reliability Monitoring')).toBeInTheDocument();
      expect(screen.getByText('OPERATIONAL')).toBeInTheDocument();
      expect(screen.getByText('PostgreSQL Database Backups')).toBeInTheDocument();
      expect(screen.getByText('aurastock_pg_20260818_120000.sql.gz')).toBeInTheDocument();
      expect(screen.getByText('aurastock_pg_20260817_120000.sql.gz')).toBeInTheDocument();
    });
  });

  it('triggers on-demand database backup and updates history with success message', async () => {
    (api.triggerBackup as any).mockResolvedValue({
      status: 'SUCCESS',
      filename: 'aurastock_pg_20260818_153000.sql.gz',
      size_formatted: '4.50 MB',
      checksum_sha256: '2c26b46b68ffc68ff99b453c1d30413413422d706483bfa0f98a5e886266e7ae',
      verified: true
    });

    render(<OperationsMonitoringPage />);

    await waitFor(() => {
      expect(screen.getByText('Trigger Backup')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText('Trigger Backup'));

    await waitFor(() => {
      expect(api.triggerBackup).toHaveBeenCalledTimes(1);
      expect(screen.getByText(/Backup created successfully: aurastock_pg_20260818_153000.sql.gz/i)).toBeInTheDocument();
    });
  });

  it('executes read-only invariant audit and displays healthy status', async () => {
    (api.runIntegrityCheck as any).mockResolvedValue({
      overall_status: 'HEALTHY',
      checks_performed: 48,
      discrepancies_count: 0,
      discrepancies: [],
      audited_at: '2026-08-18T15:30:00Z',
      invariants_verified: [
        'available = on_hand - allocated',
        'sum(ledger_deltas) == balance_cache_on_hand'
      ]
    });

    render(<OperationsMonitoringPage />);

    await waitFor(() => {
      expect(screen.getByText('Run Invariant Audit')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText('Run Invariant Audit'));

    await waitFor(() => {
      expect(api.runIntegrityCheck).toHaveBeenCalledTimes(1);
      expect(screen.getByText('All Invariants Fully Verified')).toBeInTheDocument();
      expect(screen.getByText(/48 database records audited across 5 structural invariant rules/i)).toBeInTheDocument();
    });
  });
});
