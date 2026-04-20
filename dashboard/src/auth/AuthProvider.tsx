import { useState, useEffect, ReactNode } from "react";
import { MsalProvider } from "@azure/msal-react";
import { msalInstance, isMsalConfigured } from "./msalConfig";

export function AuthProvider({ children }: { children: ReactNode }) {
  const [ready, setReady] = useState(!isMsalConfigured);

  useEffect(() => {
    if (!isMsalConfigured) return;
    msalInstance
      .initialize()
      .then(() => msalInstance.handleRedirectPromise())
      .then((resp) => {
        if (resp?.account) {
          msalInstance.setActiveAccount(resp.account);
        } else {
          const accounts = msalInstance.getAllAccounts();
          if (accounts.length > 0) msalInstance.setActiveAccount(accounts[0]);
        }
        setReady(true);
      });
  }, []);

  if (!ready) return <div style={{ padding: 40, color: "#9990b8" }}>Loading...</div>;

  if (!isMsalConfigured) {
    return <>{children}</>;
  }

  return <MsalProvider instance={msalInstance}>{children}</MsalProvider>;
}
