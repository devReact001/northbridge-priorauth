# Runbook

For whoever is on call for the Northbridge Prior Authorization Copilot. Assumes the Kubernetes deployment in
[deployment.md](deployment.md); commands use the `northbridge` namespace. This system assists reviewers and never
decides coverage, so an outage delays work but does not approve or send anything by itself. Synthetic data only.

## First look (2 minutes)

```powershell
kubectl -n northbridge get pods                     # anything not Running / Ready?
kubectl -n northbridge logs deploy/api --tail=80    # the last errors, in plain words
kubectl -n northbridge port-forward svc/api 8000:8000
curl http://localhost:8000/health                   # process is up
curl http://localhost:8000/ready                    # 200 = database reachable and models loaded
```

Then open the Dashboard in the web app: cases per day, latency per step, safeguards that fired, chart lookup and
send-out health show most problems before anyone reports them.

## Symptoms, causes and fixes

| Symptom | Likely cause | Check and fix |
|---|---|---|
| Web app says "The backend at ... is not reachable" | API pod not ready | `kubectl -n northbridge get pods`. If `api` is `0/1`, see the next rows. If it is `Running 1/1`, check the web pod's `API_KEY` matches the API's: both come from the `northbridge-secrets` secret, so restart both after any secret change. |
| `api` is `0/1 Running` for minutes | Warm-up is loading models, or failed | `logs deploy/api`. Normal first start takes about a minute. "Warm-up failed" prints the reason. `/ready` returns the same reason in its body. |
| Warm-up says `ANTHROPIC_API_KEY is not configured` | Empty key in the secret | Delete and recreate the secret (below), then `kubectl -n northbridge rollout restart deployment/api`. |
| `/ready` says the database is not reachable | Postgres pod down or its password changed | `kubectl -n northbridge get pods -l app=postgres`, `logs statefulset/postgres`. A recreated secret with a new password does not change the password inside an existing database volume; see "Rotate secrets". |
| `ImagePullBackOff` / `ErrImagePull` | The image is not visible to the cluster | The manifests use `northbridge/api:local` and `northbridge/web:local`. Docker Desktop's built-in cluster shares its image cache, so re-run `.\scripts\k8s-deploy.ps1` to rebuild. If your Docker Desktop uses the "kind" cluster type, load the images: `kind load docker-image northbridge/api:local northbridge/web:local`. |
| `CrashLoopBackOff` with `Read-only file system` in the logs | Something wants to write outside `/tmp` and the outbox | Add an emptyDir volume mounted at the path in the message (in `k8s/api.yaml`), then apply. The root filesystem is read-only on purpose. |
| Policy step finds nothing; cases escalate with "No payer policy matched" | The policy index is empty or was wiped | Reload it: `kubectl -n northbridge delete job ingest --ignore-not-found; kubectl apply -f k8s/ingest-job.yaml; kubectl -n northbridge wait --for=condition=complete job/ingest --timeout=300s` |
| A case page keeps showing "Working on it" for many minutes and the case is not in the queue | The API pod restarted mid-case; the background thread is gone | Known limitation (below). Start the case again. The stuck one never reaches a reviewer and can be ignored. |
| A case waiting for review shows no Approve button | The API was restarted with `CHECKPOINTER` not set to `postgres` | Check the ConfigMap. With `postgres` this cannot happen; the case is read-only until the API knows it again. |
| Cases fail with an Anthropic error (429, 529, timeout) | Rate limit or an outage at the model provider | The case shows the error and is not lost. Wait and start it again; check the provider's status page and your usage limits. Lower load by not running the comparison script at the same time. |
| Dashboard: chart lookup "Error" or "Patient not found" rising | The FHIR server failed to start or the patient id is not in the data | `logs deploy/api` and search for "MCP server 'fhir' did not start". The workflow keeps working on the note alone (those cases carry less evidence). Restart the API after fixing. |
| Dashboard: "Blocked" sends | A draft has `[placeholders]` left in it | Expected and safe. Nothing is sent until the reviewer fills them in with Edit. If it is frequent, look at which recommendation the drafts come from. |
| Dashboard: "reviewers changed the answer" jumps for one recommendation | The model or a prompt change made that recommendation worse | Compare the week before and after: `git log`, then the model and speed settings in the ConfigMap. Turn off `ASSESS_SPLIT` / `ASSESS_LEAN` first; they are the newest changes and are reversible with a restart. |
| Dashboard: safeguards firing more than usual | The model is making more mistakes that the code catches | Same as above. The guardrails are doing their job, but a rising rate means the model or prompt changed. |
| p95 latency doubles | Provider slowness, or output length grew | Dashboard "Where the time goes" shows which step. If `assess`, check the token line and the speed settings ([latency-and-models.md](latency-and-models.md)). |

## Routine tasks

**Rotate secrets** (the API key shared by web and api, and the Anthropic key from `.env`):

```powershell
.\scripts\k8s-deploy.ps1 -SkipBuild -SkipIngest -RotateSecrets
```

It writes a new random API key, re-reads `ANTHROPIC_API_KEY` from `.env`, and restarts api and web so both pick the new
values up. The database password is kept on purpose: it is stored inside the database volume when the database is first
created, so changing only the Secret would lock the API out. To change it, run `ALTER USER priorauth PASSWORD '...'` in
Postgres first, then update the Secret to match.

**Update the policies:** replace the PDFs in `policies/pdf`, rebuild the API image (`.\scripts\k8s-deploy.ps1`), which
also reloads the index. Run the retrieval eval (`python ..\scripts\eval_retrieval.py --modes all`) before and after.

**Change a model or a speed setting:** edit `k8s/config.yaml` (`ANTHROPIC_MODEL`, `ASSESS_MODEL`, `ASSESS_LEAN`,
`ASSESS_SPLIT`, ...), `kubectl apply -k k8s`, `kubectl -n northbridge rollout restart deployment/api`. Measure first
with `scripts/compare_models.py`. To go back, restore the value and restart.

**Back up and restore the database** (the dump is made inside the pod and copied out, which avoids PowerShell
re-encoding a binary file):

```powershell
kubectl -n northbridge exec postgres-0 -- sh -c "pg_dump -U priorauth -Fc priorauth > /tmp/priorauth.dump"
kubectl -n northbridge cp postgres-0:/tmp/priorauth.dump ./priorauth.dump

# restore into the same or a fresh deployment
kubectl -n northbridge cp ./priorauth.dump postgres-0:/tmp/priorauth.dump
kubectl -n northbridge exec postgres-0 -- pg_restore -U priorauth -d priorauth --clean --if-exists /tmp/priorauth.dump
```

Try a restore once before you need it.

**Look at what was sent out:** `kubectl -n northbridge exec deploy/api -- ls /data/outbox`.

**Stop and start without losing data:** `.\scripts\k8s-down.ps1 -Stop` then `-Start`.

## Known limitations

- **A case started but not yet at review is lost if the API pod restarts.** It runs in a background thread of that
  pod. The reviewer sees it stuck as running; starting it again fixes it. The fix is a work queue with a separate
  worker, which is also what allows more than one API replica.
- **One shared API key** between web and api; reviewers do not log in. Reviewer names are typed and recorded, not
  authenticated.
- **The network policies may not be enforced** by Docker Desktop's network plugin.
- **No alerting.** The dashboard is looked at; nothing pages anyone.

## Suggested alerts (not implemented)

Readiness failing for more than 5 minutes; a case running longer than 5 minutes; cases failing more than a few
percent in an hour; p95 time to review-ready above twice its usual level; safeguards-fired rate or changed-answer
rate moving well above its own last-30-days level; outbox volume above 80% full.
