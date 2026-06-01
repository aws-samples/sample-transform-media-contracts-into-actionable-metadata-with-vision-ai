# Authentication & User Management

[← Home](../../README.md) | [Architecture](ARCHITECTURE.md) | [Deployment](DEPLOYMENT.md) | [UI](UI.md)

---

## Overview

The system uses Amazon Cognito with admin-only user provisioning. There is no public signup — all users must be created by an administrator.

**Key facts:**
- MFA is required (TOTP authenticator app)
- Password minimum: 12 characters, must include uppercase, lowercase, digits, and symbols
- Sign-in: username or email
- Two groups control access: `admin` and `analyst`

---

## Creating Users

### Via AWS Console

1. Open the [Cognito console](https://console.aws.amazon.com/cognito/v2/idp/user-pools)
2. Select the pool named `media-contracts-users-{deployment_id}-{suffix}`
3. Click **Create user**
4. Fill in:
   - **Username**: their login name (e.g. `jsmith`)
   - **Email**: required, used for password recovery
   - **Temporary password**: set one, or check "Generate a password"
   - **Mark email as verified**: check this box
5. Click **Create user**

The user will be prompted to set a permanent password and configure MFA on first login.

### Via AWS CLI

```bash
# Get your user pool ID
USER_POOL_ID=$(aws cognito-idp list-user-pools --max-results 10 \
  --query "UserPools[?contains(Name,'media-contracts')].Id" --output text)

# Create the user
aws cognito-idp admin-create-user \
  --user-pool-id $USER_POOL_ID \
  --username jsmith \
  --user-attributes Name=email,Value=jsmith@example.com Name=email_verified,Value=true \
  --temporary-password "TempPass123!@#"

# Set a permanent password (skip the force-change-password flow)
aws cognito-idp admin-set-user-password \
  --user-pool-id $USER_POOL_ID \
  --username jsmith \
  --password "PermanentPass456!@#" \
  --permanent
```

---

## Assigning Users to Groups

Users must be in a group to access the UI. Without a group assignment, authentication succeeds but the UI has no functional access.

### Groups

| Group     | Access                                                                                 |
| --------- | -------------------------------------------------------------------------------------- |
| `admin`   | Full access — upload contracts, run analysis, browse results, KB chat, cost calculator |
| `analyst` | Read-only — browse results, KB chat                                                    |

### Via AWS Console

1. In the Cognito console, select your user pool
2. Click the **Groups** tab
3. Click `admin` or `analyst`
4. Click **Add user to group**
5. Select the user and confirm

### Via AWS CLI

```bash
# Add to admin group
aws cognito-idp admin-add-user-to-group \
  --user-pool-id $USER_POOL_ID \
  --username jsmith \
  --group-name admin

# Or add to analyst group
aws cognito-idp admin-add-user-to-group \
  --user-pool-id $USER_POOL_ID \
  --username jsmith \
  --group-name analyst
```

### Verify group membership

```bash
aws cognito-idp admin-list-groups-for-user \
  --user-pool-id $USER_POOL_ID \
  --username jsmith
```

---

## First Login Experience

1. User navigates to the application URL
2. Redirected to Cognito hosted UI login page
3. Enters username + temporary password
4. Prompted to set a permanent password (must meet policy: 12+ chars, mixed case, digits, symbols)
5. Prompted to configure MFA — scan QR code with an authenticator app (Google Authenticator, Authy, 1Password, etc.)
6. After MFA setup, redirected back to the application
7. Subsequent logins require username + password + TOTP code

---

## Session Details

| Setting              | Value   |
| -------------------- | ------- |
| Access token expiry  | 8 hours |
| ID token expiry      | 8 hours |
| Refresh token expiry | 30 days |
| Token revocation     | Enabled |

Users stay logged in for the duration of their access token. The refresh token silently renews sessions for up to 30 days without re-authentication.

---

## Removing Users

```bash
aws cognito-idp admin-delete-user \
  --user-pool-id $USER_POOL_ID \
  --username jsmith
```

Or disable without deleting (preserves the account for re-enabling later):

```bash
aws cognito-idp admin-disable-user \
  --user-pool-id $USER_POOL_ID \
  --username jsmith
```

---

## Troubleshooting

**"User does not exist" on login**
- Confirm the username is correct (case-sensitive)
- Verify the user was created in the correct pool (check `DEPLOYMENT_ID` and `STACK_SUFFIX`)

**"Password does not conform to policy"**
- Minimum 12 characters
- Must include: uppercase, lowercase, digit, and symbol

**MFA not working**
- Ensure the authenticator app's clock is synced (TOTP is time-based)
- If locked out, an admin can reset MFA:
  ```bash
  aws cognito-idp admin-set-user-mfa-preference \
    --user-pool-id $USER_POOL_ID \
    --username jsmith \
    --software-token-mfa-settings Enabled=false,PreferredMfa=false
  ```
  The user will be prompted to re-configure MFA on next login.

**User can log in but sees no data / limited access**
- Check group membership — user must be in `admin` or `analyst`
- The JWT `cognito:groups` claim is checked by the Express server

---

## How Auth Flows Through the System

```
User → Cognito (OIDC + PKCE) → JWT → Express (verifies via JWKS) → AWS APIs
                                                                      ↓
Orchestrator → Cognito (M2M client credentials) → JWT → AgentCore Gateway
```

Two separate auth flows:
1. **User → UI**: OIDC authorization code + PKCE. The browser gets tokens, Express validates them.
2. **Orchestrator → Gateway**: OAuth 2.0 client credentials (machine-to-machine). The orchestrator fetches a token from Cognito using credentials stored in Secrets Manager, then passes it to the Gateway.

Users never interact with the M2M flow — it's internal plumbing between the orchestrator and the specialist Gateway.
