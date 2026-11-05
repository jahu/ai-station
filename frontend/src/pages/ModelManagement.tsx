import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { Box, Download, Plus, Sparkles } from "lucide-react";
import { useAccount } from "../account-context";
import { PageTitle } from "../components/common";
import { Button } from "../components/ui/button";
import "./ModelManagement.css";

export default function ModelManagement({
  current,
  title,
  children,
}: {
  current: "installed" | "browse" | "setup";
  title: string;
  children: ReactNode;
}) {
  const account = useAccount();
  const canManage =
    account.mode === "operator" || account.user?.is_admin === true;
  return (
    <header className="model-management-header">
      <PageTitle
        eyebrow="YOUR LOCAL AI"
        title={title}
        action={
          current === "installed" &&
          canManage && (
            <Button asChild className="model-add-button">
              <Link to="/models/discover">
                <Plus size={19} /> Add model
              </Link>
            </Button>
          )
        }
      >
        {children}
      </PageTitle>
      <nav className="model-management-nav" aria-label="Model management">
        <Link
          to="/models"
          aria-current={current === "installed" ? "page" : undefined}
        >
          <Box size={17} /> Installed models
        </Link>
        {canManage && (
          <Link
            to="/models/discover"
            aria-current={current === "browse" ? "page" : undefined}
          >
            <Download size={17} /> Browse & download
          </Link>
        )}
        <Link
          to="/setup/models"
          aria-current={current === "setup" ? "page" : undefined}
        >
          <Sparkles size={17} /> Quick setup
        </Link>
      </nav>
    </header>
  );
}
