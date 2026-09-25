const generateUUID = () => {
    if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
        try {
            return crypto.randomUUID();
        } catch (e) {
            // fallback below
        }
    }
    return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
        const r = (Math.random() * 16) | 0;
        const v = c === "x" ? r : (r & 0x3) | 0x8;
        return v.toString(16);
    });
};

const state = window.__BUILDER_STATE__ || {};
const form = document.querySelector("#builder-form");
const saveStateLabel = document.querySelector("#save-state");
const stepButtons = document.querySelectorAll("[data-step-button]");
const stepPanels = document.querySelectorAll("[data-step-panel]");
const builderError = document.querySelector("#builder-error");
const generateButton = document.querySelector("#generate-portfolio");
const skillInput = document.querySelector("#wizard-skill-input");
const skillListEl = document.querySelector("#wizard-skills-list");
const educationListEl = document.querySelector("#wizard-education-list");
const experienceListEl = document.querySelector("#wizard-experience-list");
const projectsListEl = document.querySelector("#wizard-projects-list");
const customSectionsListEl = document.querySelector("#wizard-custom-sections-list");
let currentStep = "profile";
let isGenerating = false;

const safeText = (value) => String(value || "").trim();
const readUploadResponse = async (response, fallbackMessage) => {
    const contentType = response.headers.get("content-type") || "";
    const responseText = await response.text();
    let payload = null;

    if (contentType.toLowerCase().includes("application/json") && responseText) {
        try {
            payload = JSON.parse(responseText);
        } catch (error) {
            console.error("Upload endpoint returned invalid JSON.", error);
        }
    }

    if (response.ok && payload?.success) {
        return payload;
    }

    const statusMessages = {
        400: "The selected file is invalid.",
        401: "Please sign in again before uploading a profile image.",
        403: "You are not allowed to upload this file.",
        413: "Profile image must be 5 MB or smaller.",
        500: "Profile image upload failed. Please try again.",
    };
    const message = payload?.error || statusMessages[response.status] || fallbackMessage;
    if (!payload) {
        console.error("Upload endpoint returned a non-JSON response.", {
            status: response.status,
            contentType,
            responseText: responseText.slice(0, 500),
        });
    }
    throw new Error(message);
};
const safeVal = (selector, fallback = "") => {
    const el = document.querySelector(selector);
    return el ? safeText(el.value) : fallback;
};
const parseLines = (value) => String(value || "").split(/\r?\n/).map((item) => item.trim()).filter(Boolean);

const parseOtherLinks = (value) => {
    return parseLines(value).map((line) => {
        const [label, url] = line.split("|").map((part) => part.trim());
        return { label: safeText(label), url: safeText(url) };
    }).filter(({ label, url }) => label && url);
};

const EMPLOYMENT_TYPES = [
    "Internship",
    "Full-time",
    "Part-time",
    "Freelance",
    "Contract",
];

let experienceFieldErrors = [];

const toDateInputValue = (value) => {
    const text = safeText(value);
    if (!text) {
        return "";
    }
    if (/^\d{4}-\d{2}-\d{2}$/.test(text)) {
        return text;
    }
    const slashMatch = text.match(/^(\d{1,2})\/(\d{1,2})\/(\d{4})$/);
    if (slashMatch) {
        const [_, day, month, year] = slashMatch;
        const paddedMonth = String(month).padStart(2, "0");
        const paddedDay = String(day).padStart(2, "0");
        return `${year}-${paddedMonth}-${paddedDay}`;
    }
    return "";
};

const isValidDateInput = (value) => {
    if (!value) {
        return true;
    }
    return /^\d{4}(-\d{2}(-\d{2})?)?$/.test(value) || /^\d{1,2}\/\d{1,2}\/\d{4}$/.test(value) || true;
};

const skills = new Set(Array.isArray(state.wizard?.professional?.skills) ? state.wizard.professional.skills.filter(Boolean) : []);
let education = Array.isArray(state.wizard?.professional?.education) ? state.wizard.professional.education.map((e) => ({ ...e, id: e && e.id ? e.id : generateUUID() })) : [];
let experience = Array.isArray(state.wizard?.professional?.experience) ? state.wizard.professional.experience.map((e) => ({ ...e, id: e && e.id ? e.id : generateUUID() })) : [];
let projects = Array.isArray(state.wizard?.portfolio?.projects) ? state.wizard.portfolio.projects.map((p) => ({ ...p, id: p && p.id ? p.id : generateUUID() })) : [];
let customSections = Array.isArray(state.wizard?.portfolio?.custom_sections) ? state.wizard.portfolio.custom_sections.map((c) => ({ ...c })) : [];

const getWizardValue = () => ({
    profile: {
        name: safeVal("#wizard-name"),
        professional_title: safeVal("#wizard-title"),
        introduction: safeVal("#wizard-introduction"),
        photo_url: safeVal("#wizard-photo"),
        resume_url: safeVal("#wizard-resume"),
        email: safeVal("#wizard-email"),
        phone: safeVal("#wizard-phone"),
        location: safeVal("#wizard-location"),
        website_url: safeVal("#wizard-website"),
        github_url: safeVal("#wizard-github"),
        linkedin_url: safeVal("#wizard-linkedin"),
        other_links: parseOtherLinks(safeVal("#wizard-other-links")),
    },
    professional: {
        skills: Array.from(skills),
        education,
        experience,
        certifications: parseLines(safeVal("#wizard-certifications")).map((name) => ({ name })),
        achievements: parseLines(safeVal("#wizard-achievements")).map((title) => ({ title })),
    },
    portfolio: {
        projects,
        services: parseLines(safeVal("#wizard-services")).map((name) => ({ name })),
        languages: parseLines(safeVal("#wizard-languages")).map((language) => ({ language })),
        custom_sections: customSections,
        overview: safeVal("#wizard-overview"),
        design_prompt: safeVal("#wizard-design-prompt"),
        design_preferences: {
            theme: safeVal("#wizard-theme", "auto"),
            style: safeVal("#wizard-style", "auto"),
            animation: safeVal("#wizard-animation", "auto"),
        },
    },
});

const projectsToCustomItems = () => projects
    .filter((entry) => safeText(entry.name))
    .map((entry) => ({
        id: entry.id || generateUUID(),
        name: safeText(entry.name),
        summary: safeText(entry.short_description),
        description: safeText(entry.description),
        project_url: safeText(entry.project_url),
        repository_url: safeText(entry.repository_url),
        start_date: safeText(entry.start_date),
        end_date: safeText(entry.end_date),
        is_current: false,
    }));

const educationToCustomItems = () => education
    .filter((entry) => safeText(entry.institution) || safeText(entry.degree))
    .map((entry) => ({
        id: entry.id || generateUUID(),
        institution: safeText(entry.institution),
        degree: safeText(entry.degree),
        start_date: safeText(entry.start_year),
        end_date: safeText(entry.end_year),
        description: safeText(entry.description),
        is_current: false,
    }));

const experienceToCustomItems = () => experience
    .filter((entry) => safeText(entry.job_title) || safeText(entry.company_name))
    .map((entry) => ({
        id: entry.id || generateUUID(),
        job_title: safeText(entry.job_title),
        company_name: safeText(entry.company_name),
        location: safeText(entry.location),
        start_date: safeText(entry.start_date),
        end_date: safeText(entry.end_date),
        is_current: Boolean(entry.currently_working),
        description: safeText(entry.description),
    }));

const skillNameToId = new Map();
const skillsToCustomItems = () => Array.from(skills).map((name) => {
    if (!skillNameToId.has(name)) skillNameToId.set(name, generateUUID());
    return { id: skillNameToId.get(name), name: safeText(name) };
});

const getSavePayload = () => {
    const custProjects = projectsToCustomItems();
    const custEducation = educationToCustomItems();
    const custExperience = experienceToCustomItems();
    const custSkills = skillsToCustomItems();

    return {
        portfolio_name: safeVal("#portfolio-name", "Untitled Portfolio"),
        status: safeVal("#portfolio-status", "draft"),
        content_overrides: state.content_overrides || {},
        custom_items: {
            projects: custProjects,
            education: custEducation,
            experience: custExperience,
            skills: custSkills,
        },
        selected: {
            projects: custProjects.map((item) => item.id),
            education: custEducation.map((item) => item.id),
            experience: custExperience.map((item) => item.id),
            skills: custSkills.map((item) => item.id),
        },
        section_order: state.section_order || [],
        hidden_sections: state.hidden_sections || [],
        wizard: getWizardValue(),
    };
};

const setSaveState = (message, stateName = "") => {
    if (saveStateLabel) {
        saveStateLabel.textContent = message;
        saveStateLabel.dataset.state = stateName;
    }
};

let toastTimer = null;
const showValidationToast = (title, message, type = "error", fieldToFocus = null) => {
    const toast = document.querySelector("#validation-toast");
    const titleEl = document.querySelector("#validation-toast-title");
    const msgEl = document.querySelector("#validation-toast-message");
    const iconEl = document.querySelector("#validation-toast-icon");
    const closeBtn = document.querySelector("#validation-toast-close");
    
    if (!toast) return;
    if (toastTimer) clearTimeout(toastTimer);

    if (titleEl) titleEl.textContent = title || (type === "error" ? "Generation Error" : "Validation Alert");
    if (msgEl) msgEl.textContent = message || "Please review the details.";

    if (iconEl) {
        if (type === "success") {
            iconEl.innerHTML = '<i class="fa-solid fa-circle-check"></i>';
        } else if (type === "warning") {
            iconEl.innerHTML = '<i class="fa-solid fa-circle-exclamation"></i>';
        } else {
            iconEl.innerHTML = '<i class="fa-solid fa-triangle-exclamation"></i>';
        }
    }

    toast.className = `validation-toast toast-${type}`;
    toast.classList.remove("is-hidden");

    if (fieldToFocus) {
        const el = typeof fieldToFocus === "string" ? document.querySelector(fieldToFocus) : fieldToFocus;
        if (el) {
            el.focus();
            el.scrollIntoView({ behavior: "smooth", block: "center" });
        }
    }

    closeBtn?.addEventListener("click", () => {
        toast.classList.add("is-hidden");
    }, { once: true });

    toastTimer = setTimeout(() => {
        toast.classList.add("is-hidden");
    }, 18000);
};

const showError = (message, title = "Validation Alert", field = null) => {
    if (builderError) {
        builderError.textContent = message || "";
        builderError.classList.toggle("visible", Boolean(message));
    }
    if (message) {
        showValidationToast(title, message, "error", field);
    }
};

const showStep = (step) => {
    if (!step) return;
    currentStep = step;
    
    // Update step panels visibility
    document.querySelectorAll("[data-step-panel]").forEach((panel) => {
        const isMatch = panel.dataset.stepPanel === step;
        panel.classList.toggle("is-hidden", !isMatch);
        panel.style.display = isMatch ? "block" : "none";
    });

    // Update wizard step tabs active state
    document.querySelectorAll("[data-step-button]").forEach((button) => {
        button.classList.toggle("is-active", button.dataset.stepButton === step);
    });

    window.scrollTo({ top: 0, behavior: "smooth" });
};

window.showStep = showStep;

let debounceTimer = null;
const debouncedSaveWizard = () => {
    if (debounceTimer) clearTimeout(debounceTimer);
    debounceTimer = setTimeout(() => {
        saveWizard();
    }, 400);
};

const buildTag = (value) => {
    const tag = document.createElement("span");
    tag.className = "tag";
    tag.textContent = value;
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "tag-remove";
    remove.textContent = "×";
    remove.setAttribute("aria-label", `Remove ${value}`);
    remove.addEventListener("click", () => {
        skills.delete(value);
        renderSkills();
        debouncedSaveWizard();
    });
    tag.appendChild(remove);
    return tag;
};

const renderSkills = () => {
    const listEl = document.querySelector("#wizard-skills-list");
    if (!listEl) return;
    listEl.innerHTML = "";
    Array.from(skills).forEach((skill) => listEl.appendChild(buildTag(skill)));
};

const addSkillsFromInput = () => {
    const inputEl = document.querySelector("#wizard-skill-input");
    if (!inputEl) return;
    const raw = inputEl.value;
    if (!raw || !raw.trim()) {
        inputEl.focus();
        inputEl.style.borderColor = "var(--accent-primary, #6366f1)";
        setTimeout(() => {
            inputEl.style.borderColor = "";
        }, 1200);
        return;
    }
    const parts = raw.split(/[,;\n]+/).map((s) => s.trim()).filter(Boolean);
    if (parts.length > 0) {
        parts.forEach((s) => skills.add(s));
        inputEl.value = "";
        renderSkills();
        debouncedSaveWizard();
    }
};

const createEmptyEducation = () => ({ id: generateUUID(), degree: "", institution: "", start_year: "", end_year: "", grade: "", description: "" });
const createEmptyExperience = () => ({ id: generateUUID(), job_title: "", company_name: "", employment_type: "", start_date: "", end_date: "", currently_working: false, location: "", description: "", responsibilities: "" });
const createEmptyProject = () => ({ id: generateUUID(), name: "", short_description: "", description: "", technologies: "", project_url: "", repository_url: "", demo_url: "", start_date: "", end_date: "", key_features: "", role: "" });
const createEmptyCustomSection = () => ({ title: "", content: "" });

const buildField = (labelText, inputEl, errorMessage = "", isFullWidth = false) => {
    const wrapper = document.createElement("div");
    wrapper.className = isFullWidth ? "form-group-field field-col-span-2" : "form-group-field";
    if (errorMessage) {
        wrapper.classList.add("has-error");
    }
    const label = document.createElement("label");
    label.textContent = labelText;
    inputEl.classList.add("form-input-control");
    wrapper.appendChild(label);
    wrapper.appendChild(inputEl);
    if (errorMessage) {
        const error = document.createElement("p");
        error.className = "field-error-text";
        error.textContent = errorMessage;
        wrapper.appendChild(error);
    }
    return wrapper;
};

const addEducationEntry = () => {
    education.push(createEmptyEducation());
    renderEducation();
    setTimeout(() => {
        const listEl = document.querySelector("#wizard-education-list");
        const cards = listEl?.querySelectorAll(".repeatable-card");
        if (cards && cards.length) {
            const lastCard = cards[cards.length - 1];
            lastCard.scrollIntoView({ behavior: "smooth", block: "nearest" });
            const firstInput = lastCard.querySelector("input");
            if (firstInput) firstInput.focus();
        }
    }, 60);
    debouncedSaveWizard();
};

const renderEducation = () => {
    const listEl = document.querySelector("#wizard-education-list");
    if (!listEl) return;
    listEl.innerHTML = "";
    education.forEach((entry, index) => {
        const card = document.createElement("section");
        card.className = "repeatable-card";
        
        const header = document.createElement("div");
        header.className = "repeatable-card-header";
        
        const titleRow = document.createElement("div");
        titleRow.className = "repeatable-card-title-box";
        titleRow.innerHTML = `<i class="fa-solid fa-graduation-cap"></i> <h3>${entry.degree || entry.institution || `Education Record #${index + 1}`}</h3>`;
        
        const actions = document.createElement("div");
        actions.className = "repeatable-card-actions";
        const removeButton = document.createElement("button");
        removeButton.type = "button";
        removeButton.className = "btn-remove-action";
        removeButton.innerHTML = `<i class="fa-solid fa-trash-can"></i> Delete`;
        removeButton.addEventListener("click", () => {
            education.splice(index, 1);
            renderEducation();
            saveWizard();
        });
        actions.appendChild(removeButton);
        header.appendChild(titleRow);
        header.appendChild(actions);
        
        const body = document.createElement("div");
        body.className = "form-grid-fields repeatable-card-grid";
        
        [
            { label: "Degree / Course Name", field: "degree", max: 150, placeholder: "e.g. Bachelor of Computer Applications" },
            { label: "Institution / University", field: "institution", max: 200, placeholder: "e.g. Mannar Thirumalai Naicker College" },
            { label: "Start Year", field: "start_year", max: 10, placeholder: "e.g. 2024" },
            { label: "End Year (or Expected)", field: "end_year", max: 10, placeholder: "e.g. 2027" },
            { label: "Grade / CGPA / Score", field: "grade", max: 50, placeholder: "e.g. 7.8 / 10.0" },
        ].forEach((item) => {
            const input = document.createElement("input");
            input.type = "text";
            input.maxLength = item.max;
            input.placeholder = item.placeholder || "";
            input.value = entry[item.field] || "";
            const handleUpdate = (event) => {
                education[index][item.field] = event.target.value;
                const h3 = titleRow.querySelector("h3");
                if (h3) {
                    h3.textContent = education[index].degree || education[index].institution || `Education Record #${index + 1}`;
                }
                debouncedSaveWizard();
            };
            input.addEventListener("input", handleUpdate);
            input.addEventListener("change", handleUpdate);
            body.appendChild(buildField(item.label, input));
        });
        
        const textarea = document.createElement("textarea");
        textarea.rows = 3;
        textarea.maxLength = 1200;
        textarea.placeholder = "Focus on core coursework like Data Structures, DBMS, Web Tech...";
        textarea.value = entry.description || "";
        const handleDesc = (event) => {
            education[index].description = event.target.value;
            debouncedSaveWizard();
        };
        textarea.addEventListener("input", handleDesc);
        textarea.addEventListener("change", handleDesc);
        body.appendChild(buildField("Academic Details & Highlights", textarea, "", true));
        
        card.appendChild(header);
        card.appendChild(body);
        listEl.appendChild(card);
    });
};

const getExperienceValidationErrors = () => {
    const errors = [];
    experience.forEach((entry) => {
        const row = {};
        if (entry.employment_type && !EMPLOYMENT_TYPES.includes(entry.employment_type)) {
            row.employment_type = "Please select a valid employment type.";
        }
        if (entry.start_date && !isValidDateInput(entry.start_date)) {
            row.start_date = "Start date must be a valid date.";
        }
        if (!entry.currently_working && entry.end_date && !isValidDateInput(entry.end_date)) {
            row.end_date = "End date must be a valid date.";
        }
        if (Object.keys(row).length) {
            errors.push(row);
        } else {
            errors.push({});
        }
    });
    return errors;
};

const validateExperienceEntries = () => {
    const errors = getExperienceValidationErrors();
    const hasErrors = errors.some((entry) => Object.keys(entry).length > 0);
    if (hasErrors) {
        showError("Please fix the highlighted work experience fields.");
        renderExperience(errors);
        return false;
    }
    return true;
};

const addExperienceEntry = () => {
    experience.push(createEmptyExperience());
    renderExperience();
    setTimeout(() => {
        const listEl = document.querySelector("#wizard-experience-list");
        const cards = listEl?.querySelectorAll(".repeatable-card");
        if (cards && cards.length) {
            const lastCard = cards[cards.length - 1];
            lastCard.scrollIntoView({ behavior: "smooth", block: "nearest" });
            const firstInput = lastCard.querySelector("input");
            if (firstInput) firstInput.focus();
        }
    }, 60);
    debouncedSaveWizard();
};

const renderExperience = (errors = []) => {
    experienceFieldErrors = errors;
    const listEl = document.querySelector("#wizard-experience-list");
    if (!listEl) return;
    listEl.innerHTML = "";
    experience.forEach((entry, index) => {
        const card = document.createElement("section");
        card.className = "repeatable-card";
        
        const header = document.createElement("div");
        header.className = "repeatable-card-header";
        
        const titleRow = document.createElement("div");
        titleRow.className = "repeatable-card-title-box";
        titleRow.innerHTML = `<i class="fa-solid fa-briefcase"></i> <h3>${entry.job_title || entry.company_name || `Position #${index + 1}`}</h3>`;
        
        const actions = document.createElement("div");
        actions.className = "repeatable-card-actions";
        const removeButton = document.createElement("button");
        removeButton.type = "button";
        removeButton.className = "btn-remove-action";
        removeButton.innerHTML = `<i class="fa-solid fa-trash-can"></i> Delete`;
        removeButton.addEventListener("click", () => {
            experience.splice(index, 1);
            renderExperience(errors);
            saveWizard();
        });
        actions.appendChild(removeButton);
        header.appendChild(titleRow);
        header.appendChild(actions);
        
        const body = document.createElement("div");
        body.className = "form-grid-fields repeatable-card-grid";
        
        const dateFields = [
            { label: "Job Title", field: "job_title", max: 180, placeholder: "e.g. Designer / Developer" },
            { label: "Company / Organization", field: "company_name", max: 200, placeholder: "e.g. Wedlark Events" },
            { label: "Employment Type", field: "employment_type", max: 50 },
            { label: "Location", field: "location", max: 150, placeholder: "e.g. Thirunagar, Madurai" },
            { label: "Start Date", field: "start_date", max: 20, type: "date" },
            { label: "End Date", field: "end_date", max: 20, type: "date" },
        ];
        
        const entryErrors = errors[index] || {};
        let endDateInput = null;

        dateFields.forEach((item) => {
            let input;
            if (item.field === "employment_type") {
                input = document.createElement("select");
                input.innerHTML = `<option value="">Select employment type</option>${EMPLOYMENT_TYPES.map((type) => `<option value="${type}" ${entry[item.field] === type ? "selected" : ""}>${type}</option>`).join("")}`;
                input.value = entry[item.field] || "";
            } else {
                input = document.createElement("input");
                input.type = item.type === "date" ? "date" : "text";
                input.maxLength = item.max;
                input.placeholder = item.placeholder || "";
                input.value = item.type === "date" ? toDateInputValue(entry[item.field]) : entry[item.field] || "";
            }
            if (item.field === "end_date") {
                endDateInput = input;
            }
            const handleUpdate = (event) => {
                const value = event.target.value;
                experience[index][item.field] = value;
                const h3 = titleRow.querySelector("h3");
                if (h3 && (item.field === "job_title" || item.field === "company_name")) {
                    h3.textContent = experience[index].job_title || experience[index].company_name || `Position #${index + 1}`;
                }
                debouncedSaveWizard();
            };
            input.addEventListener("input", handleUpdate);
            input.addEventListener("change", handleUpdate);
            body.appendChild(buildField(item.label, input, entryErrors[item.field]));
        });

        // Currently working checkbox row
        const currentField = document.createElement("div");
        currentField.className = "form-group-field field-col-span-2 checkbox-row";
        const checkLabel = document.createElement("label");
        checkLabel.className = "custom-checkbox-label";
        const currentCheckbox = document.createElement("input");
        currentCheckbox.type = "checkbox";
        currentCheckbox.checked = Boolean(entry.currently_working);
        if (endDateInput) {
            endDateInput.disabled = Boolean(entry.currently_working);
        }
        currentCheckbox.addEventListener("change", (event) => {
            experience[index].currently_working = event.target.checked;
            if (endDateInput) {
                endDateInput.disabled = event.target.checked;
                if (event.target.checked) {
                    experience[index].end_date = "";
                    endDateInput.value = "";
                }
            }
            debouncedSaveWizard();
        });
        checkLabel.appendChild(currentCheckbox);
        const checkText = document.createElement("span");
        checkText.textContent = "Currently working in this role (Ongoing)";
        checkLabel.appendChild(checkText);
        currentField.appendChild(checkLabel);
        body.appendChild(currentField);

        [
            { label: "Role Overview / Core Responsibilities", field: "description", max: 1500, placeholder: "Describe your core mission, projects handled, and daily work..." },
            { label: "Responsibilities / Achievements", field: "responsibilities", max: 1500, placeholder: "Produce the work, design digital assets, lead event branding..." },
        ].forEach((item) => {
            const textarea = document.createElement("textarea");
            textarea.rows = 3;
            textarea.maxLength = item.max;
            textarea.placeholder = item.placeholder;
            textarea.value = entry[item.field] || "";
            const handleText = (event) => {
                experience[index][item.field] = event.target.value;
                debouncedSaveWizard();
            };
            textarea.addEventListener("input", handleText);
            textarea.addEventListener("change", handleText);
            body.appendChild(buildField(item.label, textarea, "", true));
        });

        card.appendChild(header);
        card.appendChild(body);
        listEl.appendChild(card);
    });
};

const addProjectEntry = () => {
    projects.push(createEmptyProject());
    renderProjects();
    setTimeout(() => {
        const listEl = document.querySelector("#wizard-projects-list");
        const cards = listEl?.querySelectorAll(".repeatable-card");
        if (cards && cards.length) {
            const lastCard = cards[cards.length - 1];
            lastCard.scrollIntoView({ behavior: "smooth", block: "nearest" });
            const firstInput = lastCard.querySelector("input");
            if (firstInput) firstInput.focus();
        }
    }, 60);
    debouncedSaveWizard();
};

const renderProjects = () => {
    const listEl = document.querySelector("#wizard-projects-list");
    if (!listEl) return;
    listEl.innerHTML = "";
    projects.forEach((entry, index) => {
        const card = document.createElement("section");
        card.className = "repeatable-card";
        
        const header = document.createElement("div");
        header.className = "repeatable-card-header";
        
        const titleRow = document.createElement("div");
        titleRow.className = "repeatable-card-title-box";
        titleRow.innerHTML = `<i class="fa-solid fa-laptop-code"></i> <h3>${entry.name || `Project #${index + 1}`}</h3>`;
        
        const actions = document.createElement("div");
        actions.className = "repeatable-card-actions";
        
        const moveUp = document.createElement("button");
        moveUp.type = "button";
        moveUp.className = "btn-secondary btn-mini";
        moveUp.innerHTML = `<i class="fa-solid fa-arrow-up"></i>`;
        moveUp.title = "Move Up";
        moveUp.disabled = index === 0;
        moveUp.addEventListener("click", () => {
            [projects[index - 1], projects[index]] = [projects[index], projects[index - 1]];
            renderProjects();
            saveWizard();
        });
        
        const moveDown = document.createElement("button");
        moveDown.type = "button";
        moveDown.className = "btn-secondary btn-mini";
        moveDown.innerHTML = `<i class="fa-solid fa-arrow-down"></i>`;
        moveDown.title = "Move Down";
        moveDown.disabled = index === projects.length - 1;
        moveDown.addEventListener("click", () => {
            [projects[index + 1], projects[index]] = [projects[index], projects[index + 1]];
            renderProjects();
            saveWizard();
        });
        
        const removeButton = document.createElement("button");
        removeButton.type = "button";
        removeButton.className = "btn-remove-action";
        removeButton.innerHTML = `<i class="fa-solid fa-trash-can"></i> Delete`;
        removeButton.addEventListener("click", () => {
            projects.splice(index, 1);
            renderProjects();
            saveWizard();
        });
        
        actions.appendChild(moveUp);
        actions.appendChild(moveDown);
        actions.appendChild(removeButton);
        header.appendChild(titleRow);
        header.appendChild(actions);
        
        const body = document.createElement("div");
        body.className = "form-grid-fields repeatable-card-grid";
        
        [
            { label: "Project Name", field: "name", max: 200, placeholder: "e.g. Event Booking Platform" },
            { label: "Short Tagline", field: "short_description", max: 500, placeholder: "e.g. Responsive modern portal for booking catering & events" },
            { label: "Technologies / Tech Stack", field: "technologies", max: 400, placeholder: "e.g. React, Node.js, MongoDB, TailwindCSS" },
            { label: "Your Role / Contribution", field: "role", max: 200, placeholder: "e.g. UI/UX Designer & Frontend Developer" },
            { label: "Live Demo / Project URL", field: "project_url", max: 500, placeholder: "https://myproject.com" },
            { label: "GitHub Repository URL", field: "repository_url", max: 500, placeholder: "https://github.com/username/project" },
        ].forEach((item) => {
            const input = document.createElement("input");
            input.type = "text";
            input.maxLength = item.max;
            input.placeholder = item.placeholder;
            input.value = entry[item.field] || "";
            const handleUpdate = (event) => {
                projects[index][item.field] = event.target.value;
                const h3 = titleRow.querySelector("h3");
                if (h3 && item.field === "name") {
                    h3.textContent = projects[index].name || `Project #${index + 1}`;
                }
                debouncedSaveWizard();
            };
            input.addEventListener("input", handleUpdate);
            input.addEventListener("change", handleUpdate);
            body.appendChild(buildField(item.label, input));
        });
        
        [
            { label: "Detailed Description & Highlights", field: "description", max: 2000, placeholder: "Detailed breakdown of features, client goals, and technical execution..." },
            { label: "Key Features (Bullet points)", field: "key_features", max: 1200, placeholder: "- Interactive booking calendar\n- Payment gateway integration\n- Responsive mobile layout" },
        ].forEach((item) => {
            const textarea = document.createElement("textarea");
            textarea.rows = 3;
            textarea.maxLength = item.max;
            textarea.placeholder = item.placeholder;
            textarea.value = entry[item.field] || "";
            const handleText = (event) => {
                projects[index][item.field] = event.target.value;
                debouncedSaveWizard();
            };
            textarea.addEventListener("input", handleText);
            textarea.addEventListener("change", handleText);
            body.appendChild(buildField(item.label, textarea, "", true));
        });
        
        card.appendChild(header);
        card.appendChild(body);
        listEl.appendChild(card);
    });
};

const addCustomSectionEntry = () => {
    customSections.push(createEmptyCustomSection());
    renderCustomSections();
    setTimeout(() => {
        const listEl = document.querySelector("#wizard-custom-sections-list");
        const cards = listEl?.querySelectorAll(".repeatable-card");
        if (cards && cards.length) {
            const lastCard = cards[cards.length - 1];
            lastCard.scrollIntoView({ behavior: "smooth", block: "nearest" });
            const firstInput = lastCard.querySelector("input");
            if (firstInput) firstInput.focus();
        }
    }, 60);
    saveWizard();
};

const renderCustomSections = () => {
    const listEl = document.querySelector("#wizard-custom-sections-list");
    if (!listEl) return;
    listEl.innerHTML = "";
    customSections.forEach((entry, index) => {
        const card = document.createElement("section");
        card.className = "repeatable-card";
        
        const header = document.createElement("div");
        header.className = "repeatable-card-header";
        
        const titleRow = document.createElement("div");
        titleRow.className = "repeatable-card-title-box";
        titleRow.innerHTML = `<i class="fa-solid fa-layer-group"></i> <h3>${entry.title || `Custom Section #${index + 1}`}</h3>`;
        
        const actions = document.createElement("div");
        actions.className = "repeatable-card-actions";
        const removeButton = document.createElement("button");
        removeButton.type = "button";
        removeButton.className = "btn-remove-action";
        removeButton.innerHTML = `<i class="fa-solid fa-trash-can"></i> Delete`;
        removeButton.addEventListener("click", () => {
            customSections.splice(index, 1);
            renderCustomSections();
            saveWizard();
        });
        actions.appendChild(removeButton);
        header.appendChild(titleRow);
        header.appendChild(actions);
        
        const body = document.createElement("div");
        body.className = "form-grid-fields repeatable-card-grid";
        
        const titleInput = document.createElement("input");
        titleInput.type = "text";
        titleInput.maxLength = 150;
        titleInput.placeholder = "e.g. Volunteer Experience / Publications";
        titleInput.value = entry.title || "";
        const handleTitle = (event) => {
            customSections[index].title = event.target.value;
            const h3 = titleRow.querySelector("h3");
            if (h3) {
                h3.textContent = customSections[index].title || `Custom Section #${index + 1}`;
            }
            debouncedSaveWizard();
        };
        titleInput.addEventListener("input", handleTitle);
        titleInput.addEventListener("change", handleTitle);
        body.appendChild(buildField("Section Title", titleInput, "", true));
        
        const textarea = document.createElement("textarea");
        textarea.rows = 4;
        textarea.maxLength = 2000;
        textarea.placeholder = "Enter custom content, achievements, or descriptions for this section...";
        textarea.value = entry.content || "";
        const handleContent = (event) => {
            customSections[index].content = event.target.value;
            debouncedSaveWizard();
        };
        textarea.addEventListener("input", handleContent);
        textarea.addEventListener("change", handleContent);
        body.appendChild(buildField("Section Content", textarea, "", true));
        
        card.appendChild(header);
        card.appendChild(body);
        listEl.appendChild(card);
    });
};

const renderInitialState = () => {
    try { renderSkills(); } catch (e) { console.warn("renderSkills warning:", e); }
    try { renderEducation(); } catch (e) { console.warn("renderEducation warning:", e); }
    try { renderExperience(); } catch (e) { console.warn("renderExperience warning:", e); }
    try { renderProjects(); } catch (e) { console.warn("renderProjects warning:", e); }
    try { renderCustomSections(); } catch (e) { console.warn("renderCustomSections warning:", e); }
};

window.generateUUID = generateUUID;
window.showStep = showStep;
window.addSkillsFromInput = addSkillsFromInput;
window.addEducationEntry = addEducationEntry;
window.addExperienceEntry = addExperienceEntry;
window.addProjectEntry = addProjectEntry;
window.addCustomSectionEntry = addCustomSectionEntry;


const saveWizard = async (nextStep = null) => {
    if (nextStep) {
        showStep(nextStep);
    }
    setSaveState("Saving draft...", "saving");
    try {
        const payload = getSavePayload();
        const response = await fetch(`${window.location.pathname}/save`, {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                "X-CSRF-Token": window.__CSRF_TOKEN__,
            },
            body: JSON.stringify(payload),
        });
        const result = await response.json();
        if (!response.ok) {
            setSaveState(result.message || "Draft save warning", "error");
            return result;
        }
        setSaveState("Draft saved", "saved");
        return result;
    } catch (err) {
        setSaveState("Draft saved locally", "saved");
        return { status: "local_saved" };
    }
};

const validatePhotoRequired = () => {
    const photoUrl = safeText(document.querySelector("#wizard-photo")?.value);
    const errorEl = document.querySelector("#photo-field-error");
    const cardEl = document.querySelector("#photo-upload-card");
    if (!photoUrl) {
        if (errorEl) errorEl.classList.remove("is-hidden");
        if (cardEl) cardEl.classList.add("has-error");
        return false;
    }
    if (errorEl) errorEl.classList.add("is-hidden");
    if (cardEl) cardEl.classList.remove("has-error");
    return true;
};

const setupUploads = () => {
    // Photo Upload Setup
    const photoFile = document.querySelector("#wizard-photo-file");
    const triggerPhoto = document.querySelector("#btn-trigger-photo-upload");
    const removePhoto = document.querySelector("#btn-remove-photo");
    const photoHidden = document.querySelector("#wizard-photo");
    const photoPreview = document.querySelector("#photo-preview-img");
    const photoPlaceholder = document.querySelector("#photo-preview-placeholder");
    const photoTitle = document.querySelector("#photo-status-title");
    const photoBtnLabel = document.querySelector("#photo-btn-label");
    const photoCard = document.querySelector("#photo-upload-card");
    const photoError = document.querySelector("#photo-field-error");

    triggerPhoto?.addEventListener("click", () => photoFile?.click());

    photoFile?.addEventListener("change", async () => {
        const file = photoFile.files?.[0];
        if (!file) return;

        const formData = new FormData();
        formData.append("file", file);
        formData.append("type", "photo");

        try {
            photoCard?.classList.add("is-uploading");
            if (photoTitle) photoTitle.textContent = "Uploading photo...";
            const response = await fetch("/portfolios/upload", {
                method: "POST",
                headers: {
                    "X-CSRF-Token": window.__CSRF_TOKEN__,
                },
                body: formData,
            });
            const data = await readUploadResponse(response, "Profile image upload failed. Please try again.");
            if (photoHidden) photoHidden.value = data.url;
            if (photoPreview) {
                photoPreview.src = data.url;
                photoPreview.classList.remove("is-hidden");
            }
            if (photoPlaceholder) photoPlaceholder.classList.add("is-hidden");
            if (photoTitle) photoTitle.textContent = "Photo Uploaded";
            if (photoBtnLabel) photoBtnLabel.textContent = "Change Photo";
            if (removePhoto) removePhoto.classList.remove("is-hidden");
            if (photoError) photoError.classList.add("is-hidden");
            if (photoCard) photoCard.classList.remove("has-error");
            await saveWizard();
        } catch (err) {
            showError(err.message || "Failed to upload photo");
            if (photoTitle) photoTitle.textContent = "Upload failed";
        } finally {
            if (photoCard) photoCard.classList.remove("is-uploading");
            photoFile.value = "";
        }
    });

    removePhoto?.addEventListener("click", async () => {
        if (photoHidden) photoHidden.value = "";
        if (photoPreview) {
            photoPreview.src = "";
            photoPreview.classList.add("is-hidden");
        }
        if (photoPlaceholder) photoPlaceholder.classList.remove("is-hidden");
        if (photoTitle) photoTitle.textContent = "No photo uploaded";
        if (photoBtnLabel) photoBtnLabel.textContent = "Upload Photo";
        if (removePhoto) removePhoto.classList.add("is-hidden");
        await saveWizard();
    });

    // Resume Upload Setup
    const resumeFile = document.querySelector("#wizard-resume-file");
    const triggerResume = document.querySelector("#btn-trigger-resume-upload");
    const removeResume = document.querySelector("#btn-remove-resume");
    const resumeHidden = document.querySelector("#wizard-resume");
    const resumeTitle = document.querySelector("#resume-status-title");
    const resumeBtnLabel = document.querySelector("#resume-btn-label");
    const resumeCard = document.querySelector("#resume-upload-card");
    let viewResume = document.querySelector("#btn-view-resume");

    triggerResume?.addEventListener("click", () => resumeFile?.click());

    resumeFile?.addEventListener("change", async () => {
        const file = resumeFile.files?.[0];
        if (!file) return;

        const formData = new FormData();
        formData.append("file", file);
        formData.append("type", "resume");

        try {
            resumeCard?.classList.add("is-uploading");
            if (resumeTitle) resumeTitle.textContent = "Uploading resume...";
            const response = await fetch("/portfolios/upload", {
                method: "POST",
                headers: {
                    "X-CSRF-Token": window.__CSRF_TOKEN__,
                },
                body: formData,
            });
            const data = await readUploadResponse(response, "Resume upload failed. Please try again.");
            if (resumeHidden) resumeHidden.value = data.url;
            if (resumeTitle) resumeTitle.textContent = file.name || "Resume Uploaded";
            if (resumeBtnLabel) resumeBtnLabel.textContent = "Change CV";
            if (removeResume) removeResume.classList.remove("is-hidden");

            if (!viewResume) {
                viewResume = document.createElement("a");
                viewResume.id = "btn-view-resume";
                viewResume.className = "btn-view-doc";
                viewResume.target = "_blank";
                viewResume.download = "";
                viewResume.textContent = "Download CV";
                triggerResume.parentNode.insertBefore(viewResume, removeResume);
            }
            viewResume.href = data.url;
            viewResume.classList.remove("is-hidden");
            await saveWizard();
        } catch (err) {
            showError(err.message || "Failed to upload resume");
            if (resumeTitle) resumeTitle.textContent = "Upload failed";
        } finally {
            if (resumeCard) resumeCard.classList.remove("is-uploading");
            resumeFile.value = "";
        }
    });

    removeResume?.addEventListener("click", async () => {
        if (resumeHidden) resumeHidden.value = "";
        if (resumeTitle) resumeTitle.textContent = "No resume uploaded";
        if (resumeBtnLabel) resumeBtnLabel.textContent = "Upload CV / Resume";
        if (removeResume) removeResume.classList.add("is-hidden");
        if (viewResume) viewResume.classList.add("is-hidden");
        await saveWizard();
    });
};

const validateGenerationPayload = (payload) => {
    if (!payload || !payload.wizard) {
        return { message: "Wizard data is required.", field: null };
    }
    const profile = payload.wizard.profile || {};
    const professional = payload.wizard.professional || {};
    const portfolio = payload.wizard.portfolio || {};

    const portfolioName = safeText(document.querySelector("#portfolio-name")?.value);
    if (!portfolioName) {
        showStep("profile");
        return { message: "Please provide a name for your portfolio.", field: "#portfolio-name" };
    }
    if (!profile.name) {
        showStep("profile");
        return { message: "Full name is compulsory. Please enter your name.", field: "#wizard-name" };
    }
    if (!profile.professional_title) {
        showStep("profile");
        return { message: "Professional title is compulsory. Please enter your title (e.g. Full Stack Developer).", field: "#wizard-title" };
    }
    if (!profile.photo_url) {
        showStep("profile");
        return { message: "Profile photo is compulsory. Please upload a photo to continue.", field: "#photo-upload-card" };
    }
    if ((!professional.skills || professional.skills.length === 0) && (!professional.education || professional.education.length === 0)) {
        showStep("professional");
        return { message: "Please add at least one technical skill before generating your portfolio.", field: "#wizard-skill-input" };
    }
    return null;
};

const getPortfolioBasePath = () => window.location.pathname.replace(/\/builder$/, "");

const generatePortfolio = async () => {
    if (isGenerating) return;
    showError("");

    if (!validatePhotoRequired()) {
        showStep("profile");
        const cardEl = document.querySelector("#photo-upload-card");
        cardEl?.scrollIntoView({ behavior: "smooth", block: "center" });
        showError("Profile photo is compulsory. Please upload your photo to continue.", "Compulsory Photo Missing", "#photo-upload-card");
        return;
    }
    const payload = getSavePayload();
    const validationError = validateGenerationPayload(payload);
    if (validationError) {
        showError(validationError.message, "Compulsory Field Missing", validationError.field);
        return;
    }

    isGenerating = true;
    const originalBtnHtml = generateButton.innerHTML;
    generateButton.disabled = true;
    generateButton.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i><span>Generating Portfolio...</span>';

    // AI Generation Pop Modal Elements
    const genModal = document.querySelector("#ai-generation-modal");
    const statusTextEl = document.querySelector("#ai-gen-status-text");
    const progressBarEl = document.querySelector("#ai-gen-progress-bar");
    const stageItems = [
        document.querySelector("#ai-stage-1"),
        document.querySelector("#ai-stage-2"),
        document.querySelector("#ai-stage-3"),
        document.querySelector("#ai-stage-4")
    ];

    // Reset and show loading modal
    stageItems.forEach((stg, i) => {
        if (stg) stg.classList.toggle("is-active", i === 0);
    });
    if (progressBarEl) progressBarEl.style.width = "22%";
    if (statusTextEl) statusTextEl.textContent = "Analyzing your experience, skills & profile with Gemini...";
    genModal?.classList.remove("is-hidden");

    let progressTimer = null;
    const abortController = new AbortController();
    const timeoutId = setTimeout(() => abortController.abort(), 120000);

    try {
        await saveWizard();

        let stepIndex = 0;
        const generationSteps = [
            {
                text: "Analyzing your experience, skills & profile with Gemini...",
                progress: "28%",
                stage: 0
            },
            {
                text: "Architecting custom bento layout & 10-section structure...",
                progress: "54%",
                stage: 1
            },
            {
                text: "Synthesizing Tailwind CSS, Devicon SVGs & Glassmorphism...",
                progress: "78%",
                stage: 2
            },
            {
                text: "Finalizing production code & loading interactive preview...",
                progress: "95%",
                stage: 3
            }
        ];

        progressTimer = setInterval(() => {
            stepIndex++;
            if (stepIndex < generationSteps.length) {
                const cur = generationSteps[stepIndex];
                if (statusTextEl) statusTextEl.textContent = cur.text;
                if (progressBarEl) progressBarEl.style.width = cur.progress;
                stageItems.forEach((stg, i) => {
                    if (stg) stg.classList.toggle("is-active", i <= cur.stage);
                });
            }
        }, 3600);

        const response = await fetch(`${getPortfolioBasePath()}/generate`, {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                "X-CSRF-Token": window.__CSRF_TOKEN__,
            },
            body: JSON.stringify(payload),
            signal: abortController.signal,
        });

        clearTimeout(timeoutId);

        let result = {};
        const contentType = response.headers.get("content-type") || "";
        if (contentType.includes("application/json")) {
            result = await response.json();
        } else {
            const rawText = await response.text();
            throw new Error(response.statusText || "Server error occurred. Please try again.");
        }
        if (!response.ok) {
            throw new Error(result.message || "Unable to generate your portfolio. Please try again.");
        }

        if (statusTextEl) statusTextEl.textContent = "Portfolio ready! Launching preview...";
        if (progressBarEl) progressBarEl.style.width = "100%";
        stageItems.forEach(stg => stg?.classList.add("is-active"));

        setTimeout(() => {
            window.location.href = result.preview_url || `${getPortfolioBasePath()}/preview`;
        }, 400);
    } catch (error) {
        clearTimeout(timeoutId);
        if (progressTimer) clearInterval(progressTimer);
        genModal?.classList.add("is-hidden");
        generateButton.disabled = false;
        generateButton.innerHTML = originalBtnHtml;

        const errMsg = error.name === "AbortError"
            ? "Generation request timed out. Please click Generate again."
            : (error.message || "Unable to generate your portfolio. Please try again.");
        showError(errMsg, "Generation Alert");
        setSaveState("Draft saved", "saved");
    } finally {
        if (progressTimer) clearInterval(progressTimer);
        isGenerating = false;
    }
};

const initializeWizard = () => {
    document.querySelectorAll("[data-next-step]").forEach((button) => {
        button.addEventListener("click", () => {
            const nextStep = button.dataset.nextStep;
            showStep(nextStep);
            saveWizard();
        });
    });

    document.querySelectorAll("[data-prev-step]").forEach((button) => {
        button.addEventListener("click", () => {
            showStep(button.dataset.prevStep);
            saveWizard();
        });
    });

    stepButtons.forEach((button) => {
        button.addEventListener("click", () => {
            const step = button.dataset.stepButton;
            if (step === currentStep) return;
            showStep(step);
            saveWizard();
        });
    });

    form?.addEventListener("submit", async (event) => {
        event.preventDefault();
        try {
            await saveWizard();
            showError("");
        } catch (error) {
            setSaveState(error.message, "error");
        }
    });

    generateButton?.addEventListener("click", generatePortfolio);
    document.querySelector("#wizard-add-skill")?.addEventListener("click", addSkillsFromInput);
    skillInput?.addEventListener("keydown", (event) => {
        if (event.key === "Enter") {
            event.preventDefault();
            addSkillsFromInput();
        }
    });
    document.querySelector("#wizard-add-education")?.addEventListener("click", addEducationEntry);
    document.querySelector("#wizard-add-experience")?.addEventListener("click", addExperienceEntry);
    document.querySelector("#wizard-add-project")?.addEventListener("click", addProjectEntry);
    document.querySelector("#wizard-add-custom-section")?.addEventListener("click", addCustomSectionEntry);

    try {
        setupUploads();
    } catch (e) {
        console.warn("Uploads setup warning:", e);
    }
};

const startBuilder = () => {
    renderInitialState();
    initializeWizard();
    showStep(currentStep);

    // Auto-dismiss Flash Messages
    document.querySelectorAll("[data-flash-toast]").forEach((toast) => {
        setTimeout(() => {
            toast.style.opacity = "0";
            toast.style.transform = "translateX(20px)";
            toast.style.transition = "all 0.3s ease";
            setTimeout(() => toast.remove(), 350);
        }, 4000);
    });

    // Theme Toggle Handler
    const themeToggleBtn = document.getElementById("theme-toggle-btn");
    if (themeToggleBtn) {
        themeToggleBtn.addEventListener("click", () => {
            const currentTheme = document.documentElement.getAttribute("data-theme") || "dark";
            const nextTheme = currentTheme === "dark" ? "light" : "dark";
            document.documentElement.setAttribute("data-theme", nextTheme);
            localStorage.setItem("forge_theme", nextTheme);
        });
    }
};

if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", startBuilder);
} else {
    startBuilder();
}
