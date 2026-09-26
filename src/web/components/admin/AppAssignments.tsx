import Link from "next/link";
import type { EntraAppAssignmentRef } from "@/lib/types";

export function AppAssignments({ items }: { items: EntraAppAssignmentRef[] | undefined }) {
  const rows = items || [];
  return (
    <section className="panel-pad mt-6">
      <h3 className="text-sm font-medium">Enterprise apps ({rows.length})</h3>
      <p className="mt-1 text-xs text-mist-500">
        Direct assignments on the enterprise application (Users and groups in Entra). Nested group membership is not
        expanded.
      </p>
      <ul className="mt-4 space-y-2 text-sm">
        {rows.map((row) => (
          <li
            key={`${row.application_id}:${row.app_role_id}`}
            className="flex flex-wrap items-center justify-between gap-3 border-b border-white/5 py-2"
          >
            <span>
              <Link href={`/entra/apps/${row.application_id}`} className="hover:text-glass">
                {row.display_name}
              </Link>
              <span className="ml-2 text-xs text-mist-500">{row.app_role_name}</span>
              {row.has_app_registration && <span className="chip ml-2">App registration</span>}
              {row.is_microsoft && <span className="chip ml-2">Microsoft</span>}
            </span>
            {row.assignment_required && <span className="text-xs text-mist-500">Assignment required</span>}
          </li>
        ))}
        {!rows.length && (
          <li className="text-mist-500">Not assigned to any enterprise apps in the last directory sync.</li>
        )}
      </ul>
    </section>
  );
}
