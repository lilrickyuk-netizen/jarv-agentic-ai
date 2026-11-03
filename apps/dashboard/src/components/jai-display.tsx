'use client';

import { showCard, useScreenCard } from '@/lib/screen-signal';

/** What JAI has put on screen while talking: shown beside the intelligence field until Richard closes it or JAI
 * shows something else. Empty when JAI has shown nothing. */
export function JaiDisplay() {
  const card = useScreenCard();
  if (!card) return null;
  return (
    <section className="jai-display" aria-label={`JAI is showing: ${card.title}`} data-kind={card.kind}>
      <header className="jai-display-head">
        <div>
          <p className="eyebrow">JAI · ON SCREEN</p>
          <h3>{card.title}</h3>
          {card.subtitle && <small>{card.subtitle}</small>}
        </div>
        <div className="jai-display-actions">
          {card.link && <a className="text-link" href={card.link}>Open ↗</a>}
          <button type="button" className="jai-display-close" onClick={() => showCard(null)} aria-label="Close">×</button>
        </div>
      </header>
      {card.sections.map((section, index) => (
        <div className="jai-display-section" key={`${section.heading ?? ''}-${index}`}>
          {section.heading && <h4>{section.heading}</h4>}
          {section.rows && (
            <table>
              {section.columns && <thead><tr>{section.columns.map((c, i) => <th key={i}>{c}</th>)}</tr></thead>}
              <tbody>{section.rows.map((row, r) => (
                <tr key={r}>{row.map((cell, c) => <td key={c} data-status={c === 1 ? String(cell ?? '') : undefined}>{String(cell ?? '')}</td>)}</tr>
              ))}</tbody>
            </table>
          )}
          {section.items && <ul>{section.items.map((item, i) => <li key={i}>{item}</li>)}</ul>}
          {section.code !== undefined && <pre>{section.code}</pre>}
          {/* Only JAI's own image links (its backend, through this dashboard) are shown. */}
          {section.image?.startsWith('/api/backend/') && (
            // eslint-disable-next-line @next/next/no-img-element
            <img className="jai-display-image" src={section.image} alt={card.title} />
          )}
        </div>
      ))}
    </section>
  );
}
