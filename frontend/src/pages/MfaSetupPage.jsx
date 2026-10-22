import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import QRCode from "qrcode";
import { useAuth } from "../hooks/useAuth";
import { confirmMfa, setupMfa } from "../api/auth";
import { extractApiError } from "../utils/apiError";

// MFA is mandatory. Reached automatically after the first password change, or
// whenever the backend answers "mfa_setup_required" (e.g. after an admin reset).
export default function MfaSetupPage() {
  const { user, refreshMe, logout } = useAuth();
  const navigate = useNavigate();

  const [secret, setSecret] = useState("");
  const [qrDataUrl, setQrDataUrl] = useState("");
  const [code, setCode] = useState("");
  const [error, setError] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [isSubmitting, setIsSubmitting] = useState(false);
  // Each setup call creates a new secret, so it must run exactly once per visit
  // (React StrictMode runs effects twice in development).
  const setupStarted = useRef(false);

  useEffect(() => {
    if (setupStarted.current) return;
    setupStarted.current = true;

    async function start() {
      try {
        const data = await setupMfa();
        setSecret(data.secret);
        setQrDataUrl(await QRCode.toDataURL(data.otpauth_uri, { margin: 1, width: 220 }));
      } catch (err) {
        if (err?.response?.status === 409) {
          // Already enabled (e.g. in another tab).
          await refreshMe();
          navigate("/dashboard", { replace: true });
          return;
        }
        setError(extractApiError(err, "Could not start MFA setup. Please reload the page."));
      } finally {
        setIsLoading(false);
      }
    }
    start();
  }, [navigate, refreshMe]);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError("");
    setIsSubmitting(true);
    try {
      await confirmMfa(code.trim());
      await refreshMe();
      navigate("/dashboard", { replace: true });
    } catch (err) {
      setError(
        err?.response?.status === 429
          ? "Too many attempts. Please wait a minute and try again."
          : extractApiError(err, "Invalid or expired code.")
      );
      setCode("");
    } finally {
      setIsSubmitting(false);
    }
  };

  // Groups of four characters are easier to type into an app by hand.
  const groupedSecret = secret.match(/.{1,4}/g)?.join(" ") ?? "";

  return (
    <div className="auth-page">
      <div className="auth-card">
        <div className="auth-header">
          <p className="auth-kicker">{user?.workspace?.name || "Accessa"}</p>
          <h1>Set up two-factor authentication</h1>
          <p className="auth-subtitle">
            Accessa requires a second factor for every account. Scan the QR code with
            any authenticator app that supports TOTP codes (for example Google
            Authenticator or Microsoft Authenticator), then enter the 6-digit code it shows.
          </p>
        </div>

        {isLoading ? (
          <div className="empty-state">Preparing your setup key…</div>
        ) : secret ? (
          <>
            <div className="mfa-qr">
              {qrDataUrl && <img src={qrDataUrl} alt="QR code for your authenticator app" width="220" height="220" />}
            </div>

            <div className="form-group">
              <span className="detail-label">Can't scan? Enter this key manually</span>
              <code className="mfa-secret">{groupedSecret}</code>
              <span className="form-hint">Account: {user?.email} · Issuer: Accessa · Time-based</span>
            </div>

            <form className="auth-form" onSubmit={handleSubmit}>
              <div className="form-group">
                <label htmlFor="mfa_code">6-digit code</label>
                <input
                  id="mfa_code"
                  className="mfa-code-input"
                  type="text"
                  inputMode="numeric"
                  autoComplete="one-time-code"
                  pattern="[0-9]{6}"
                  maxLength={6}
                  placeholder="123456"
                  value={code}
                  onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))}
                  required
                  autoFocus
                />
              </div>

              {error && <div className="auth-error">{error}</div>}

              <button className="btn btn-primary auth-submit" type="submit" disabled={isSubmitting || code.length !== 6}>
                {isSubmitting ? "Checking..." : "Confirm and continue"}
              </button>
            </form>
          </>
        ) : (
          error && <div className="auth-error">{error}</div>
        )}

        <p className="auth-switch">
          <button type="button" className="link-button" onClick={logout}>
            Log out
          </button>
        </p>
      </div>
    </div>
  );
}
