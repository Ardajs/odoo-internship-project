/** @odoo-module **/

import { Interaction } from "@web/public/interaction";
import { registry } from "@web/core/registry";

export class InternshipVerificationToken extends Interaction {
    static selector = ".o_internship_verification_form";

    setup() {
        const fragment = new URLSearchParams(window.location.hash.slice(1));
        const secret = fragment.get("token");
        if (secret) {
            this.el.querySelector('input[name="secret"]').value = secret;
        }
        if (window.location.hash) {
            window.history.replaceState(
                null,
                document.title,
                `${window.location.pathname}${window.location.search}`
            );
        }
    }
}

registry
    .category("public.interactions")
    .add(
        "internship_logbook.verification_token",
        InternshipVerificationToken
    );
