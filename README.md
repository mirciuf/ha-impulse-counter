# 🔢 Impulse Counter pentru Home Assistant

Contor de apă sau gaz folosind senzori de contact magnetic (ușă/geam). Numără impulsurile de la senzor și calculează consumul în m³.

---

## ✅ Funcționalități

- **Suport apă și gaz** — cu iconuri și unități corespunzătoare
- **Factor de multiplicare configurabil** — câte impulsuri = 1 m³
- **Index inițial** — pornești de la valoarea contorului fizic real
- **Persistarea datelor** — valoarea se păstrează la restart HA
- **Card Lovelace custom** — afișaj modern cu statistici detaliate
- **Serviciu de resetare** — poți reseta contorul oricând
- **Configurare din UI** — fără YAML, totul din interfață

---

## 📦 Instalare

### Metoda 1: Manual (recomandat pentru început)

1. Copiați folderul `custom_components/impulse_counter` în directorul `/config/custom_components/` din Home Assistant:
   ```
   /config/custom_components/impulse_counter/
   ├── __init__.py
   ├── config_flow.py
   ├── const.py
   ├── manifest.json
   ├── sensor.py
   ├── services.yaml
   ├── strings.json
   └── translations/
       ├── en.json
       └── ro.json
   ```

2. Copiați folderul `www/impulse-counter-card` în directorul `/config/www/`:
   ```
   /config/www/impulse-counter-card/
   └── impulse-counter-card.js
   ```

3. Restartați Home Assistant.

### Metoda 2: HACS (după ce adăugați ca repository custom)

1. Mergeți la HACS → Integrări → ⋮ → Custom repositories
2. Adăugați URL-ul repository-ului, categorie: Integration
3. Instalați "Impulse Counter"
4. Restartați Home Assistant

---

## ⚙️ Configurare

### Pasul 1: Adăugați integrarea

1. Mergeți la **Setări → Dispozitive & Servicii → + Adaugă Integrare**
2. Căutați **"Impulse Counter"**
3. Completați formularul:

| Câmp | Descriere | Exemplu |
|------|-----------|---------|
| **Numele contorului** | Nume descriptiv | `Contor Apă Rece` |
| **Senzor de contact** | Entitatea senzorului magnetic | `binary_sensor.contor_apa` |
| **Tipul contorului** | Apă sau Gaz | `Apă` |
| **Factor multiplicare** | Impulsuri per m³ | `100` (100 impulsuri = 1 m³) |
| **Index inițial** | Valoarea curentă de pe contor | `1234.567` |

### Pasul 2: Adăugați cardul Lovelace

1. Mergeți la **Setări → Dashboard → Resurse**
2. Adăugați resursa:
   - URL: `/local/impulse-counter-card/impulse-counter-card.js`
   - Tip: `JavaScript Module`

3. Adăugați cardul în dashboardul vostru:
   ```yaml
   type: custom:impulse-counter-card
   entity: sensor.contor_apa_rece
   ```

---

## 🔧 Conexiune fizică

```
Contorul de apă/gaz
        │
    Reed Switch (contact magnetic)
    (se deschide/închide la fiecare impuls)
        │
   GPIO / Zigbee / Z-Wave
        │
   Binary Sensor în HA
   (door/window/opening)
        │
   Impulse Counter Integration
```

**Tipuri de senzori compatibili:**
- Senzori de geam/ușă Zigbee (SONOFF, Aqara, IKEA)
- Senzori Z-Wave
- Senzori ESP8266/ESP32 prin ESPHome
- Orice binary_sensor cu device_class: door/window/opening

---

## 📊 Atribute disponibile

Entitatea senzor creată va avea aceste atribute:

```yaml
total_pulses: 12450        # Total impulsuri numărate
multiplier: 100            # Factor de multiplicare
initial_value: 1234.567    # Index inițial setat
source_entity: binary_sensor.contor_apa  # Senzorul sursă
meter_type: water          # water sau gas
last_reset: "2024-01-15T10:30:00+00:00"  # Ultimul impuls
```

---

## 🔄 Servicii disponibile

### `impulse_counter.reset_counter`

Resetează contorul cu opțional o nouă valoare inițială:

```yaml
service: impulse_counter.reset_counter
target:
  entity_id: sensor.contor_apa_rece
data:
  new_initial_value: 1500.000
```

---

## 📈 Integrare cu Energy Dashboard

Entitățile create sunt compatibile cu **Energy Dashboard** din HA:

1. Mergeți la **Setări → Dashboard Energy**
2. La **Consumul de apă**, adăugați entitatea voastră
3. Selectați `sensor.contor_apa_rece`

---

## ❓ Probleme frecvente

**Senzorul meu nu apare în dropdown:**
- Verificați că are `device_class: door`, `window` sau `opening`
- Dacă nu apare, toți senzorii binari vor fi afișați ca fallback

**Contorul numără de două ori:**
- Verificați că senzorul nu trimite mai multe state changes per impuls
- Adăugați debounce în ESPHome dacă folosiți GPIO direct

**Valorile se pierd la restart:**
- Verificați că integrarea `restore_state` funcționează în HA
- Nu ștergeți fișierul `.storage/core.restore_state`

---

## 📝 Licență

MIT License — utilizare liberă și modificare
