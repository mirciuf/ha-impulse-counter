/**
 * Impulse Counter Card for Home Assistant
 * Displays water/gas meter readings with detailed stats
 */

class ImpulseCounterCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._config = {};
    this._hass = null;
  }

  static getConfigElement() {
    return document.createElement("impulse-counter-card-editor");
  }

  static getStubConfig() {
    return { entity: "" };
  }

  setConfig(config) {
    if (!config.entity) {
      throw new Error("Trebuie să specificați o entitate");
    }
    this._config = config;
    this.render();
  }

  set hass(hass) {
    this._hass = hass;
    this.render();
  }

  getMeterIcon(meterType) {
    return meterType === "gas"
      ? `<svg viewBox="0 0 24 24" fill="currentColor" width="32" height="32">
          <path d="M17.66 11.2c-.23-.3-.51-.56-.77-.82-.67-.6-1.43-1.03-2.07-1.66C13.33 7.26 13 4.85 13.95 3c-.95.23-1.78.75-2.49 1.32-2.59 2.08-3.61 5.75-2.39 8.9.04.1.08.2.08.33 0 .22-.15.42-.35.5-.23.1-.47.04-.66-.12-.06-.05-.1-.1-.15-.17-1.1-1.43-1.28-3.48-.53-5.12C5.89 10 5 12.3 5.14 14.47c.04.5.1 1 .27 1.5.14.6.4 1.2.72 1.73 1.18 1.9 3.26 3.23 5.5 3.27 2.36.05 4.61-1.06 5.86-3.03.6-.94.87-2.06.8-3.18-.06-.86-.36-1.62-.63-2.36Z"/>
        </svg>`
      : `<svg viewBox="0 0 24 24" fill="currentColor" width="32" height="32">
          <path d="M12 2c-5.33 4.55-8 8.48-8 11.8 0 4.98 3.8 8.2 8 8.2s8-3.22 8-8.2c0-3.32-2.67-7.25-8-11.8z"/>
        </svg>`;
  }

  getMeterColor(meterType) {
    return meterType === "gas" ? "#ff6b35" : "#2196f3";
  }

  formatValue(value) {
    if (value === undefined || value === null || isNaN(parseFloat(value))) {
      return "—";
    }
    return parseFloat(value).toFixed(3);
  }

  render() {
    if (!this._config || !this._hass) return;

    const entityId = this._config.entity;
    const state = this._hass.states[entityId];

    if (!state) {
      this.shadowRoot.innerHTML = `
        <ha-card>
          <div style="padding:16px;color:var(--error-color)">
            Entitatea "${entityId}" nu a fost găsită.
          </div>
        </ha-card>`;
      return;
    }

    const attrs = state.attributes;
    const meterType = attrs.meter_type || "water";
    const value = state.state;
    const unit = attrs.unit_of_measurement || "m³";
    const name = attrs.friendly_name || entityId;
    const pulses = attrs.total_pulses || 0;
    const multiplier = attrs.multiplier || 1;
    const initialValue = attrs.initial_value || 0;
    const lastReset = attrs.last_reset
      ? new Date(attrs.last_reset).toLocaleString("ro-RO")
      : "—";
    const sourceEntity = attrs.source_entity || "—";

    const color = this.getMeterColor(meterType);
    const icon = this.getMeterIcon(meterType);
    const meterLabel = meterType === "gas" ? "Contor Gaz" : "Contor Apă";

    const isUnavailable = state.state === "unavailable" || state.state === "unknown";

    this.shadowRoot.innerHTML = `
      <style>
        :host {
          display: block;
        }
        ha-card {
          border-radius: 12px;
          overflow: hidden;
          box-shadow: var(--ha-card-box-shadow, none);
        }
        .card-header {
          background: linear-gradient(135deg, ${color}22 0%, ${color}11 100%);
          border-bottom: 2px solid ${color}44;
          padding: 16px 20px;
          display: flex;
          align-items: center;
          gap: 12px;
        }
        .header-icon {
          color: ${color};
          display: flex;
          align-items: center;
        }
        .header-text {
          flex: 1;
        }
        .header-title {
          font-size: 14px;
          font-weight: 600;
          color: var(--secondary-text-color);
          text-transform: uppercase;
          letter-spacing: 0.5px;
        }
        .header-name {
          font-size: 18px;
          font-weight: 700;
          color: var(--primary-text-color);
          margin-top: 2px;
        }
        .card-body {
          padding: 20px;
        }
        .value-section {
          display: flex;
          align-items: flex-end;
          gap: 8px;
          margin-bottom: 20px;
          padding: 16px;
          background: var(--secondary-background-color);
          border-radius: 10px;
          border-left: 4px solid ${color};
        }
        .main-value {
          font-size: 42px;
          font-weight: 800;
          color: ${color};
          line-height: 1;
          font-family: monospace;
        }
        .main-unit {
          font-size: 18px;
          font-weight: 600;
          color: var(--secondary-text-color);
          margin-bottom: 6px;
        }
        .unavailable {
          color: var(--disabled-color);
          font-style: italic;
        }
        .stats-grid {
          display: grid;
          grid-template-columns: 1fr 1fr;
          gap: 12px;
          margin-bottom: 16px;
        }
        .stat-item {
          background: var(--secondary-background-color);
          border-radius: 8px;
          padding: 12px;
        }
        .stat-label {
          font-size: 11px;
          font-weight: 600;
          color: var(--secondary-text-color);
          text-transform: uppercase;
          letter-spacing: 0.5px;
          margin-bottom: 4px;
        }
        .stat-value {
          font-size: 16px;
          font-weight: 700;
          color: var(--primary-text-color);
        }
        .stat-value.accent {
          color: ${color};
        }
        .source-section {
          background: var(--secondary-background-color);
          border-radius: 8px;
          padding: 10px 12px;
          display: flex;
          align-items: center;
          gap: 8px;
        }
        .source-dot {
          width: 8px;
          height: 8px;
          border-radius: 50%;
          background: var(--success-color);
          flex-shrink: 0;
        }
        .source-dot.off {
          background: var(--disabled-color);
        }
        .source-text {
          font-size: 12px;
          color: var(--secondary-text-color);
          flex: 1;
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
        }
        .last-pulse {
          font-size: 11px;
          color: var(--tertiary-text-color);
          text-align: right;
          margin-top: 8px;
        }
      </style>

      <ha-card>
        <div class="card-header">
          <div class="header-icon">${icon}</div>
          <div class="header-text">
            <div class="header-title">${meterLabel}</div>
            <div class="header-name">${name}</div>
          </div>
        </div>

        <div class="card-body">
          <div class="value-section">
            <div class="main-value ${isUnavailable ? "unavailable" : ""}">
              ${isUnavailable ? "—" : this.formatValue(value)}
            </div>
            <div class="main-unit">${unit}</div>
          </div>

          <div class="stats-grid">
            <div class="stat-item">
              <div class="stat-label">Total Impulsuri</div>
              <div class="stat-value accent">${pulses.toLocaleString("ro-RO")}</div>
            </div>
            <div class="stat-item">
              <div class="stat-label">Factor Multiplicare</div>
              <div class="stat-value">${multiplier} imp/m³</div>
            </div>
            <div class="stat-item">
              <div class="stat-label">Index Inițial</div>
              <div class="stat-value">${this.formatValue(initialValue)} m³</div>
            </div>
            <div class="stat-item">
              <div class="stat-label">Consum Măsurat</div>
              <div class="stat-value accent">${this.formatValue(parseFloat(value) - parseFloat(initialValue))} m³</div>
            </div>
          </div>

          <div class="source-section">
            <div class="source-dot ${isUnavailable ? "off" : ""}"></div>
            <div class="source-text">Senzor: ${sourceEntity}</div>
          </div>

          <div class="last-pulse">Ultimul impuls: ${lastReset}</div>
        </div>
      </ha-card>
    `;
  }

  getCardSize() {
    return 4;
  }
}

customElements.define("impulse-counter-card", ImpulseCounterCard);

window.customCards = window.customCards || [];
window.customCards.push({
  type: "impulse-counter-card",
  name: "Impulse Counter Card",
  description: "Card pentru afișarea contorului de apă sau gaz bazat pe impulsuri",
  preview: false,
  documentationURL: "https://github.com/yourusername/ha-impulse-counter",
});

console.info(
  `%c IMPULSE-COUNTER-CARD %c v1.0.0 `,
  "color: white; background: #2196f3; font-weight: 700;",
  "color: #2196f3; background: white; font-weight: 700;"
);
