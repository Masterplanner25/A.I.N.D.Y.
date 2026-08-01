import React from "react";
import { NavLink } from "react-router-dom";

import { safeMap } from "../../utils/safe";
import { surfacePalette as P } from "./SurfacePrimitives";

// The platform SPA registers eight routes and, until this component, rendered no links
// between them. Only /platform/flows was reachable — via the "Open platform" button in
// the product app — so Agent Console, Approvals, Registry, Observability, Health,
// Executions and Trace existed, worked, and could be reached only by typing a URL.
export const PLATFORM_LINKS = [
  { to: "/agent", label: "Agent Console" },
  { to: "/approvals", label: "Approvals" },
  { to: "/registry", label: "Agent Registry" },
  { to: "/flows", label: "Flow Engine" },
  { to: "/executions", label: "Executions" },
  { to: "/observability", label: "Observability" },
  { to: "/health", label: "Health" },
  { to: "/trace", label: "Trace" },
  { to: "/users", label: "Admin Users" },
  { to: "/webhooks", label: "Webhooks" },
];

const linkStyle = (isActive) => ({
  padding: "8px 14px",
  borderRadius: 6,
  fontSize: 13,
  fontWeight: isActive ? 700 : 500,
  textDecoration: "none",
  whiteSpace: "nowrap",
  color: isActive ? P.accent : P.muted,
  background: isActive ? P.accentSoft : "transparent",
  border: `1px solid ${isActive ? P.borderStrong : "transparent"}`,
});

export default function PlatformNav() {
  return (
    <nav
      aria-label="Platform"
      style={{
        display: "flex",
        alignItems: "center",
        gap: 6,
        flexWrap: "wrap",
        padding: "10px 16px",
        marginBottom: 4,
        background: P.panel,
        borderBottom: `1px solid ${P.border}`,
        position: "sticky",
        top: 0,
        zIndex: 20,
      }}>

      <span
        style={{
          fontSize: 12,
          fontWeight: 700,
          letterSpacing: 1,
          textTransform: "uppercase",
          color: P.muted,
          marginRight: 10,
        }}>
        Platform
      </span>

      {safeMap(PLATFORM_LINKS, (link) =>
      <NavLink key={link.to} to={link.to} style={({ isActive }) => linkStyle(isActive)}>
          {link.label}
        </NavLink>
      )}

      <a
        href="/"
        style={{
          ...linkStyle(false),
          marginLeft: "auto",
          color: P.muted,
        }}>
        ← Back to app
      </a>
    </nav>);

}
