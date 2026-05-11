# JottaBackup GUI

Web-basert administrasjonsgrensesnitt for [Jottacloud CLI](https://docs.jottacloud.com/en/collections/178055-our-command-line-tool) på TrueNAS Scale.

Appen kjører som en Docker-container og hentes automatisk fra **GitHub Container Registry (ghcr.io)** — du trenger ikke bygge noe lokalt på TrueNAS-serveren.

## Funksjoner

- Passordinnlogging
- Opprett, rediger og slett backup-jobber med cron-plan
- Kjør backup manuelt eller automatisk etter plan
- Live statusoppdatering og fremdriftslinje
- Filtrert logger
- Jottacloud CLI-tilkoblingsstatus
- Automatisk ny image ved push til GitHub

---

## Del 1 – Sett opp GitHub-repositoriet

### Steg 1 – Opprett repo på GitHub

1. Gå til [github.com/new](https://github.com/new)
2. Gi repoet navnet **`jottacloud-gui`** (må matche image-navnet i konfigurasjonen)
3. Sett det til **Private** eller Public – begge fungerer
4. Klikk **Create repository**

### Steg 2 – Last opp filene

Du kan enten bruke GitHub Desktop, VS Code eller terminalen:

```bash
# I prosjektmappen (der du har filene fra Cowork):
git init
git add .
git commit -m "Initial commit – JottaBackup GUI"
git branch -M main
git remote add origin https://github.com/DITT_BRUKERNAVN/jottacloud-gui.git
git push -u origin main
```

> Bytt ut `DITT_BRUKERNAVN` med ditt faktiske GitHub-brukernavn.

### Steg 3 – Gjør pakken offentlig i GitHub Container Registry

Etter at GitHub Actions har kjørt og bygget imagen (ca. 3–5 min etter push):

1. Gå til `https://github.com/DITT_BRUKERNAVN?tab=packages`
2. Klikk på pakken **jottacloud-gui**
3. Gå til **Package settings → Danger Zone → Change visibility**
4. Sett den til **Public**

> **Alternativt:** Behold den privat og generer et Personal Access Token (PAT) med `read:packages`-tilgang, og legg det inn som `imagePullSecret` i TrueNAS (se avansert seksjon nedenfor).

---

## Del 2 – Sjekk at imagen er bygget

Etter push vil GitHub Actions automatisk:
- Bygge Docker-imagen for linux/amd64 og linux/arm64
- Publisere den til `ghcr.io/DITT_BRUKERNAVN/jottacloud-gui:latest`

Sjekk fremdriften under **Actions**-fanen i GitHub-repoet ditt. Grønt hakemerke = klar.

---

## Del 3 – Sett opp på TrueNAS Scale

### Steg 1 – Opprett datamapper

Logg inn på TrueNAS med SSH og opprett mappene:

```bash
mkdir -p /mnt/tank/apps/jottabackup/data
mkdir -p /mnt/tank/apps/jottabackup/logs
```

> Bytt `tank` med ditt faktiske pool-navn.

### Steg 2 – Logg inn på Jottacloud (én gang)

```bash
docker run --rm -it \
  -v /mnt/tank/apps/jottabackup/data:/data \
  ghcr.io/DITT_BRUKERNAVN/jottacloud-gui:latest \
  jotta-cli login
```

Følg instruksjonene. Token lagres i `/mnt/tank/apps/jottabackup/data/.jotta/` og brukes automatisk av appen videre.

### Steg 3 – Installer som Custom App i TrueNAS

1. Gå til **Apps → Discover Apps → Custom App**
2. Gi appen navnet `jottabackup`
3. Klikk **Edit YAML** og lim inn innholdet fra `truenas/ix-values.yaml`
4. Gjør disse endringene i YAML-en:
   - Bytt `DITT_GITHUB_BRUKERNAVN` → ditt faktiske GitHub-brukernavn (2 steder)
   - Sett `APP_PASSWORD` til et valgfritt passord
   - Sett `SECRET_KEY` til en lang tilfeldig streng
   - Juster `hostPath`-verdiene til ditt pool-navn
5. Klikk **Install**

### Steg 4 – Åpne GUI

Åpne nettleser og gå til:

```
http://<truenas-ip>:3600
```

Logg inn med passordet du satte i `APP_PASSWORD`.

---

## Del 4 – Legg til mapper som skal sikkerhetskopieres

For at appen skal kunne lese mappene dine, må de mountes inn i containeren. I `ix-values.yaml`, legg til under `persistence:` og `volumeMounts:`:

```yaml
# I persistence-seksjonen:
tank-dokumenter:
  enabled: true
  type: hostPath
  hostPath: /mnt/tank/dokumenter
  mountPath: /mnt/tank/dokumenter
  readOnly: true

# I volumeMounts-seksjonen:
- name: tank-dokumenter
  mountPath: /mnt/tank/dokumenter
```

Deretter kan du i GUI-en opprette en backup-jobb med kildemappe `/mnt/tank/dokumenter`.

---

## Oppdatering av appen

Når du gjør endringer og pusher til GitHub, bygger GitHub Actions automatisk ny image. For å oppdatere containeren på TrueNAS:

```bash
# Hent ny image
docker pull ghcr.io/DITT_BRUKERNAVN/jottacloud-gui:latest

# Restart containeren (hvis du bruker docker-compose)
docker compose up -d
```

Eller i TrueNAS GUI: **Apps → jottabackup → Update**.

---

## Avansert: Privat image med PAT

Hvis du beholder imagen privat på ghcr.io:

1. Gå til [github.com/settings/tokens](https://github.com/settings/tokens) → **Generate new token (classic)**
2. Gi den tillatelsen `read:packages`
3. I TrueNAS, logg inn på ghcr.io i containeren:
   ```bash
   echo "DITT_PAT" | docker login ghcr.io -u DITT_BRUKERNAVN --password-stdin
   ```

---

## Cron-plan eksempler

| Plan | Beskrivelse |
|---|---|
| `0 3 * * *` | Daglig kl. 03:00 |
| `0 2 * * 0` | Ukentlig søndag kl. 02:00 |
| `0 1 1 * *` | Månedlig 1. dag kl. 01:00 |
| `30 22 * * 1-5` | Hverdager kl. 22:30 |

Bruk [crontab.guru](https://crontab.guru) for å lage din egen.

---

## Prosjektstruktur

```
.
├── .github/
│   └── workflows/
│       └── docker-build.yml   # GitHub Actions: bygg og push til ghcr.io
├── backend/
│   ├── app.py                 # Flask API + backup-motor
│   └── requirements.txt
├── frontend/
│   ├── index.html             # Single-page app
│   └── static/
│       ├── css/style.css
│       └── js/app.js
├── truenas/
│   ├── app.yaml               # TrueNAS app-metadata
│   └── ix-values.yaml         # TrueNAS Custom App YAML
├── .gitignore
├── Dockerfile
├── docker-compose.yml
└── README.md
```

---

## Miljøvariabler

| Variabel | Standard | Beskrivelse |
|---|---|---|
| `APP_PASSWORD` | `jotta123` | Passord for GUI-innlogging |
| `SECRET_KEY` | `change-me-please` | Flask session-nøkkel (sett til noe tilfeldig) |
| `DATA_DIR` | `/data` | Jobbdefinisjoner og Jotta-token |
| `LOG_DIR` | `/logs` | Loggar |
| `PORT` | `3600` | HTTP-port |
| `TZ` | `Europe/Oslo` | Tidssone for cron-planer |
