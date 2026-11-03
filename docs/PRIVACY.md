# Branchline privacy and data handling

This guide describes the source implementation as of 3 November 2026. Deployment choices belong to the operator. It is an architecture guide, not a completed legal privacy notice or a certification. The operator must publish its identity, contact route, actual processors, configured regions, retention policies, and customer terms before accepting live customer data.

## Two different modes

**Public demonstration:** the interface provides sample scenarios and prewritten illustrative reports. Creating a demo scenario does not run MiroFish or analyse the brief. Draft text, imported text, and a connected workspace token are held in the current browser tab's memory rather than deliberately stored in browser local storage. Reloading or closing the tab ends that in-memory session. A report explicitly exported by the user is a separate downloaded copy under their control. The web host still receives ordinary page and asset requests and may maintain its own access records.

**Connected pilot:** an operator provisions a workspace token, hosts the gateway and private MiroFish engine, and supplies model and Zep credentials. After the visitor connects the gateway and confirms external processing, submitting a run sends the reviewed brief to the gateway and onward for live processing. This build has no public self-service account signup or paid subscription activation.

## What the local privacy preview does

The interface can mask common email-address and phone-number patterns before a brief is sent. It shows the reviewed brief to the visitor before submission. This is pattern-based redaction, not comprehensive anonymisation: names, locations, customer stories, unique events, identifiers in unusual formats, and commercially sensitive details may remain. Inspect the whole reviewed brief, including title, question, audience, and context. Do not assume a clean detection count means a document contains no sensitive data.

Importing a text brief reads the file in the browser. A later live submission transmits the reviewed text; “read locally” is not a promise that the text will never leave the device.

## Connected data flow

```text
Visitor's browser
  Reviewed brief + workspace bearer token
    -> HTTPS gateway controlled by operator
       Encrypted request/report payload in SQLite
       Workspace and run metadata
         -> Private MiroFish engine
            Source text, graph references, personas, simulation files, reports
              -> Operator-configured model provider
              -> Zep Cloud knowledge graph
```

TLS must be configured by the operator for public gateway access. The engine container must remain on a private network; it has no independently suitable public multi-tenant authentication layer. Provider credentials belong on the server, not in browser code or a source repository. The browser's workspace token grants access to that workspace: do not share it or put it in a URL.

## Controls implemented in the gateway

| Control | What it covers | Limit |
| --- | --- | --- |
| Workspace bearer authentication | Authenticated capabilities, run creation, run reads, and deletion | Tokens are operator-provisioned; there is no user identity, MFA, role model, or per-person audit trail |
| Workspace-scoped record queries | Run access requires the authenticated workspace ID | Sharing a workspace token shares its authority; operational access still needs restriction |
| Hashed stored tokens | SQLite stores a SHA-256 token hash rather than a recoverable token | A stolen live bearer token can still be used until replaced |
| Fernet payload encryption | Run request, result, error, and upstream-reference payload stored in SQLite | Gateway decrypts for use; one operator-held key serves the pilot; this does not encrypt the whole database or engine volume |
| Bounded requests and jobs | Request-size checks, exact CORS origin list, round and entity limits, active-run caps, request limiting and job timeout | These do not guarantee a maximum provider invoice or eliminate pre-simulation costs |
| Safer error responses | Gateway avoids returning upstream bodies or invalid input content in validation errors | Host infrastructure and provider logging still need their own configuration |
| Engine wrapper logging change | Disables standard Python logging before importing the engine; removes browser CORS response headers | Does not remove simulation output, direct stdout/stderr, worker artifacts, infrastructure logs, or provider records |
| Gateway response cache headers | Responses request no-store behavior | This does not control screenshots, exports, browser extensions, compromised devices, or all intermediary behavior |

Workspace names, IDs, run status, timestamps, credit balances, and some other metadata are not protected by the private-payload encryption. Operating-system permissions, encrypted host storage, backup controls, TLS, and secret management remain necessary. Keep the encryption key separate from database backups and plan key recovery; losing it makes stored encrypted content unreadable.

MiroFish writes source documents and simulation artifacts to its filesystem. Those files are plaintext from the application's point of view. Use encrypted volumes and restricted operator access before live use. The supplied wrapper does not turn this into end-to-end encrypted inference: the gateway, engine, model provider, and graph service can process readable content as needed.

## Retention and deletion

The request can select a gateway retention period from 1 to 30 days. The gateway records an expiry deadline from the creation time and scans expired terminal runs while its process is running. Active work is not removed by that scan; a running, unavailable, or stopped gateway can delay cleanup. Configure monitoring and operational cleanup rather than promising an exact deletion instant.

Deletion of a terminal run attempts to stop remaining upstream simulation work and calls the engine's report and project deletion endpoints. A project deletion can also request deletion of its referenced Zep graph. The returned receipt distinguishes acknowledged deletion, records not created, and cleanup that needs operator attention. An acknowledgement is a response from an API, not independent evidence that all copies have disappeared.

MiroFish has no simulation-artifact deletion API in this pinned integration. Persona files, simulation logs, and other artifacts require an operator procedure. The gateway's deletion endpoint therefore cannot promise complete engine erasure. Operators must inspect pending-cleanup receipts and remove the remaining files with appropriate care, including files associated with failed, interrupted, or timed-out preparation.

When supported upstream cleanup remains pending, the gateway retains a separate encrypted cleanup task with resource references and acknowledgements, without the customer brief or generated report. This is intentional limited retention for remediation. Operators can list and retry these tasks through `python -m server.cleanup`; they must verify manual artifact removal before resolving a task. See the [gateway operating guide](../server/README.md#privacy-scope-and-deletion). A task marked resolved is an operator attestation, not an automated proof of remote erasure.

Deleting a gateway row does not revoke report exports or screenshots. Encrypted database pages may also remain in WAL files, snapshots, and backups until those copies expire. Deleting encryption keys requires a deliberate key-management procedure and cannot be substituted for an unverified “delete everything” claim.

The model provider and Zep have independent retention, logging, and backup policies. Current Zep documentation describes internal copies that can survive context deletion, including disaster-recovery backups up to 365 days and graph write logs up to 90 days. Verify the deployed API/SDK version, account configuration, and contract; these are not time limits enforced by Branchline. [Zep retention documentation](https://help.getzep.com/context-retention)

## Claims this build does not establish

Do not advertise zero retention, immediate complete erasure, end-to-end encrypted inference, Australian-only processing, automatic provider training exclusion, or a compliance certification. Hosting the gateway in Australia alone does not constrain model and graph processing to Australia. Customer-provided provider credentials also do not automatically change a provider's terms.

The privacy receipt identifies the current processing categories and gateway retention setting; the operator still needs to populate precise provider names, regions, policy links, and backup terms. A receipt should preserve uncertainty rather than convert an unavailable cleanup check into a success claim.

Synthetic participants are fictional. Their statements and percentages are not evidence of actual people's views or calibrated predictions. Publish this limitation with reports, and use real customer research to validate decisions.

## Operator settings before live use

Configure exact allowed HTTPS origins, a restricted private engine address, a securely generated encryption key, persistent encrypted storage, provider keys and model revision, access-controlled backups and their expiry, and the identity of the person responsible for cleanup. Restrict gateway and engine administrator access. Disable request-body capture in proxies and monitoring. Publish an accurate list of providers and processing locations.

Use a small, non-sensitive test project to verify the entire live path, a cross-workspace access denial, a failed run, restart behavior, expiration, a deletion receipt, and manual artifact cleanup. Keep public demo access separate from the gateway's operator-issued workspace access.
