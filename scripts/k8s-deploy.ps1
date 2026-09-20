<#
Deploys the whole system to a local Kubernetes cluster (Docker Desktop: Settings > Kubernetes > Enable Kubernetes).

  .\scripts\k8s-deploy.ps1                 build both images, create secrets, apply, load the policies, wait
  .\scripts\k8s-deploy.ps1 -SkipBuild      reuse the images already built
  .\scripts\k8s-deploy.ps1 -SkipIngest     do not reload the policy PDFs into the database
  .\scripts\k8s-deploy.ps1 -SkipBuild -SkipIngest -RotateSecrets    new API key, re-read the Anthropic key from .env

Run from anywhere; it moves to the project root itself. Needs docker and kubectl on PATH and a .env with
ANTHROPIC_API_KEY (the file is only read here; it is never copied into an image or a manifest).
#>
param(
  [switch]$SkipBuild,
  [switch]$SkipIngest,
  [switch]$RotateSecrets,               # new API key and the Anthropic key from .env; the database password is kept
  [string]$Context = "docker-desktop"   # refuse to deploy anywhere else unless you say so
)
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)
$ns = "northbridge"

function Run([string]$what, [scriptblock]$cmd) {
  Write-Host "==> $what" -ForegroundColor Cyan
  & $cmd
  if ($LASTEXITCODE -ne 0) { throw "Failed: $what" }
}

$current = (kubectl config current-context).Trim()
if ($current -ne $Context) {
  throw "kubectl is pointed at '$current', not '$Context'. Switch with: kubectl config use-context $Context (or pass -Context to deploy to a different cluster on purpose)."
}

if (-not $SkipBuild) {
  Run "Build the API image (first build downloads torch and two models, about 5 to 10 minutes)" { docker build -t northbridge/api:local -f backend/Dockerfile . }
  Run "Build the web image" { docker build -t northbridge/web:local frontend }
}

Run "Create the namespace" { kubectl apply -f k8s/namespace.yaml }

# --ignore-not-found prints nothing and exits 0 when the secret is absent (no stderr, so no PowerShell error record).
$existing = kubectl -n $ns get secret northbridge-secrets --ignore-not-found -o name
if (-not $existing -or $RotateSecrets) {
  $anthropic = $null
  foreach ($line in Get-Content .env) {
    if ($line -match '^\s*ANTHROPIC_API_KEY\s*=\s*(.+?)\s*$') { $anthropic = $Matches[1].Trim('"').Trim("'") }
  }
  if (-not $anthropic -or $anthropic -eq "your-key-here") { throw "ANTHROPIC_API_KEY is missing in .env" }
  function New-Secret { -join ((48..57) + (65..90) + (97..122) | Get-Random -Count 32 | ForEach-Object { [char]$_ }) }
  # The database password is stored inside the database volume when it is first created, so a rotation keeps it.
  $dbPassword = $null
  if ($existing) {
    $encoded = kubectl -n $ns get secret northbridge-secrets -o jsonpath='{.data.POSTGRES_PASSWORD}'
    if ($encoded) { $dbPassword = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($encoded)) }
  }
  if (-not $dbPassword) { $dbPassword = New-Secret }
  Run "Create or update the secret (Anthropic key from .env, random API key, database password)" {
    kubectl -n $ns create secret generic northbridge-secrets `
      --from-literal=ANTHROPIC_API_KEY=$anthropic `
      --from-literal=API_KEY=$(New-Secret) `
      --from-literal=POSTGRES_PASSWORD=$dbPassword `
      --dry-run=client -o yaml | kubectl apply -f -
  }
} else {
  Write-Host "==> Secret northbridge-secrets already exists; keeping it" -ForegroundColor Cyan
}

Run "Apply the manifests" { kubectl apply -k k8s }
Run "Wait for the database" { kubectl -n $ns rollout status statefulset/postgres --timeout=240s }

if (-not $SkipIngest) {
  kubectl -n $ns delete job ingest --ignore-not-found | Out-Null
  Run "Load the policy PDFs" { kubectl apply -f k8s/ingest-job.yaml }
  Run "Wait for the policies to load" { kubectl -n $ns wait --for=condition=complete job/ingest --timeout=300s }
}

# The API and web pods are created by the apply above; a rebuilt image needs a restart to be picked up.
if (-not $SkipBuild -or $RotateSecrets) {
  kubectl -n $ns rollout restart deployment/api deployment/web | Out-Null
}
Run "Wait for the API (loads the models before it reports ready)" { kubectl -n $ns rollout status deployment/api --timeout=400s }
Run "Wait for the web app" { kubectl -n $ns rollout status deployment/web --timeout=180s }

Write-Host ""
Write-Host "Ready: http://localhost:8080" -ForegroundColor Green
Write-Host "If that does not load, try: kubectl -n $ns port-forward svc/web 8080:8080"
kubectl -n $ns get pods
