<#
Removes the deployment. By default the database and outbox volumes are deleted with the namespace.
  .\scripts\k8s-down.ps1          delete everything, including saved cases
  .\scripts\k8s-down.ps1 -Stop    scale the API and web to zero but keep the data (start again with -Start)
  .\scripts\k8s-down.ps1 -Start
#>
param([switch]$Stop, [switch]$Start, [string]$Context = "docker-desktop")
$ErrorActionPreference = "Stop"
$ns = "northbridge"
$current = (kubectl config current-context).Trim()
if ($current -ne $Context) { throw "kubectl is pointed at '$current', not '$Context'." }
if ($Stop) {
  kubectl -n $ns scale deployment/api deployment/web --replicas=0
} elseif ($Start) {
  kubectl -n $ns scale deployment/api deployment/web --replicas=1
  kubectl -n $ns rollout status deployment/api --timeout=400s
} else {
  Write-Host "This deletes the namespace, including the database (saved cases, the policy index) and the outbox." -ForegroundColor Yellow
  kubectl delete namespace $ns
}
