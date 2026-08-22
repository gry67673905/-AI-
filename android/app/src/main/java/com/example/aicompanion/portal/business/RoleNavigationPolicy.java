package com.example.aicompanion.portal.business;

import com.example.aicompanion.portal.model.PortalContract.Role;

import java.util.Arrays;
import java.util.Collections;
import java.util.List;

/** Native-owned role navigation; the WebView cannot promote itself by changing DOM state. */
public final class RoleNavigationPolicy {
    public List<String> sections(Role role) {
        if (role == Role.CITIZEN) {
            return Arrays.asList("consultation", "services", "applications", "appointments", "profile");
        }
        if (role == Role.STAFF) {
            return Arrays.asList("staff_tasks", "staff_handoffs", "profile");
        }
        if (role == Role.ADMIN) {
            return Arrays.asList("admin_overview", "admin_catalog", "admin_people", "admin_knowledge", "admin_audit", "profile");
        }
        return Arrays.asList("consultation", "services", "login");
    }

    public boolean canNavigate(Role role, String section) {
        return section != null && sections(role == null ? Role.ANONYMOUS : role).contains(section);
    }
}
