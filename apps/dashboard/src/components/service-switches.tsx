'use client';

/**
 * JAI's services: Richard switches the heavy ones (image generator, natural voice, video maker, document reader,
 * browser, code understanding) on and off here, to share the computer's memory. Backed by
 * GET/POST /api/operations/switches, which starts and stops only those services through JAI's restricted Docker
 * proxy and records each change in the audit log.
 */
import { useCallback, useEffect, useState } from 'react';
import { apiClient } from '@/lib/api';

export interface ServiceSwitch {
  service: string;
  label: string;
  about: string;
  installed: boolean;
  on: boolean;
  status: string;
}

interface Switches {
  available: boolean;
  reason?: string;
  switches: ServiceSwitch[];
  memory_available_gb?: number;
  memory_total_gb?: number;
}

export function ServiceSwitches() {
  const [data, setData] = useState<Switches | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    const result = await apiClient.get<Switches>('/api/operations/switches');
    if (result.error) setError(result.error);
    else setData(result.data ?? null);
  }, []);

  useEffect(() => {
    load();
    const interval = window.setInterval(load, 15000);
    return () => window.clearInterval(interval);
  }, [load]);

  const flip = async (item: ServiceSwitch) => {
    setBusy(item.service);
    setError(null);
    const result = await apiClient.post(`/api/operations/switches/${encodeURIComponent(item.service)}`, { on: !item.on });
    if (result.error) setError(`${item.label}: ${result.error}`);
    await load();
    setBusy(null);
  };

  return (
    <article className="cockpit-panel switch-panel" aria-label="JAI's services">
      <div className="panel-heading">
        <div><p className="eyebrow">COMPUTER</p><h2>JAI&apos;s services</h2></div>
        {data?.memory_total_gb ? (
          <span className="switch-memory">{data.memory_available_gb} GB free of {data.memory_total_gb} GB</span>
        ) : null}
      </div>
      {error && <p className="switch-error" role="alert">{error}</p>}
      {data && !data.available && <p className="switch-error">{data.reason}</p>}
      {!data && !error && <div className="empty-state">Loading…</div>}
      <ul className="switch-list">
        {data?.switches.map((item) => (
          <li key={item.service} className="switch-row">
            <div>
              <strong>{item.label}</strong>
              <small>{item.installed ? item.about : 'Not installed on this computer'}</small>
            </div>
            <button
              type="button"
              role="switch"
              aria-checked={item.on}
              aria-label={`${item.label} ${item.on ? 'on' : 'off'}`}
              className={`switch-toggle${item.on ? ' is-on' : ''}`}
              disabled={!item.installed || busy !== null}
              onClick={() => flip(item)}
            >
              {busy === item.service ? (item.on ? 'Stopping…' : 'Starting…') : item.on ? 'On' : 'Off'}
            </button>
          </li>
        ))}
      </ul>
    </article>
  );
}

export default ServiceSwitches;
