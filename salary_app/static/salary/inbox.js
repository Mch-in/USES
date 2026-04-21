// Print window/iframe styles — global, used from both DOMContentLoaded and $(document).ready
var PRINT_STYLES = '<style type="text/css">' +
    '.print-container{font-family:\'Segoe UI\',sans-serif;padding:20px;max-width:600px;margin:auto;border:1px solid #000;}' +
    '.print-container h3{text-align:center;margin-bottom:25px;}' +
    '.print-container .detail-row{display:flex;justify-content:space-between;padding:10px 0;border-bottom:1px solid #eee;align-items:flex-start;}' +
    '.print-container .detail-row:last-child{border-bottom:none;}' +
    '.print-container .detail-label{font-weight:bold;color:#555;padding-right:20px;}' +
    '.print-container .detail-value{text-align:right;}' +
    '.print-container .comment-value{white-space:pre-wrap;text-align:left;flex:1;}' +
    '.print-container .signature-section{margin-top:60px;display:flex;justify-content:flex-end;}' +
    '.print-container .signature-block{width:45%;text-align:center;}' +
    '.print-container .signature-line{border-bottom:1px solid #000;height:25px;margin-bottom:5px;}' +
    '.print-container .signature-caption{font-size:0.8em;color:#555;}' +
    '</style>';

// Print via hidden iframe (shared for salary payments and expenses)
function printWithIframe(printContent) {
    var iframe = document.createElement('iframe');
    iframe.style.cssText = 'position:absolute;width:0;height:0;border:0;left:-9999px;top:0';
    document.body.appendChild(iframe);
    var frameDoc = iframe.contentWindow.document;
    frameDoc.open();
    frameDoc.write('<html><head><title>Print</title>' + PRINT_STYLES + '</head><body>' + printContent + '</body></html>');
    frameDoc.close();
    setTimeout(function () {
        iframe.contentWindow.focus();
        iframe.contentWindow.print();
        setTimeout(function () { document.body.removeChild(iframe); }, 500);
    }, 100);
}

document.addEventListener("DOMContentLoaded", function () {

    const amountInput = document.getElementById("id_amount");


    // Toast notifications
    window.showToast = function (message, type = "success") {
        const toast = document.getElementById("fixed-toast");
        const toastMessage = document.getElementById("toast-message");

        if (!toast || !toastMessage) {
            console.warn("Toast element not found");
            return;
        }

        // Clear previous animation classes
        toast.classList.remove("toast-error-animate", "toast-success-animate");

        if (type === "error") {
            // On error show animated "Error" label
            toastMessage.textContent = (window.JS_TRANSLATIONS && window.JS_TRANSLATIONS.error) || "Error";
            toast.classList.remove("bg-success", "bg-danger", "d-none");
            toast.classList.add("bg-danger");
            // Add animation class
            toast.classList.add("toast-error-animate");
            // Auto-hide after 4s (longer for animation)
            setTimeout(() => {
                toast.classList.add("d-none");
                toast.classList.remove("toast-error-animate");
            }, 4000);
        } else {
            toastMessage.textContent = message;
            toast.classList.remove("bg-success", "bg-danger", "d-none");
            toast.classList.add("bg-success");
            if (type === "loading") {
                toast.classList.remove("toast-success-animate");
            } else {
                toast.classList.add("toast-success-animate");
                setTimeout(() => {
                    toast.classList.add("d-none");
                    toast.classList.remove("toast-success-animate");
                }, 3000);
            }
        }
    }

    function formatEta(seconds) {
        if (seconds <= 0 || !Number.isFinite(seconds)) return "";
        var m = Math.floor(seconds / 60);
        var s = Math.floor(seconds % 60);
        const minText = (window.JS_TRANSLATIONS && window.JS_TRANSLATIONS.min) || "min";
        const secText = (window.JS_TRANSLATIONS && window.JS_TRANSLATIONS.sec) || "sec";
        if (m > 0) return " ~" + m + " " + minText;
        return " ~" + s + " " + secText;
    }

    function normalizeAmountRaw(value) {
        return String(value || '').replace(/[ \u00A0\u202F]/g, '').replace(',', '.');
    }

    function formatAmountInputValue(value, decimalLimit) {
        var raw = normalizeAmountRaw(value);
        var cleaned = '';
        var hasDot = false;

        for (var i = 0; i < raw.length; i++) {
            var ch = raw.charAt(i);
            if (/\d/.test(ch)) {
                cleaned += ch;
            } else if (ch === '.' && !hasDot) {
                cleaned += ch;
                hasDot = true;
            }
        }

        if (cleaned === '') {
            return '';
        }

        var parts = cleaned.split('.');
        var integerPart = parts[0] || '0';
        var decimalPart = parts.length > 1 ? parts[1] : undefined;
        if (decimalPart !== undefined && typeof decimalLimit === 'number') {
            decimalPart = decimalPart.slice(0, decimalLimit);
        }

        integerPart = integerPart.replace(/\B(?=(\d{3})+(?!\d))/g, ' ');
        return decimalPart !== undefined ? integerPart + '.' + decimalPart : integerPart;
    }

    if (amountInput) {
        amountInput.addEventListener("input", function (e) {
            var input = e.target;
            input.value = formatAmountInputValue(input.value, 2);
        });

        amountInput.addEventListener("blur", function (e) {
            var value = normalizeAmountRaw(e.target.value);
            if (value && !value.includes('.')) {
                e.target.value = e.target.value + '.00';
            }
        });
    }

    $(document).on('input', '#expenseModal input[name="amount"]', function () {
        $(this).val(formatAmountInputValue($(this).val(), 2));
    });

    // On submit, strip all spaces and NBSP from amount to avoid server-side validation errors
    $(document).on('submit', '#expenseModal form', function () {
        var $amount = $('#expenseModal input[name="amount"]');
        if ($amount.length) {
            $amount.val(normalizeAmountRaw($amount.val()));
        }
    });


    // Sales row toggle
    document.querySelectorAll(".toggle-btn").forEach(button => {
        const monthKey = button.getAttribute("data-month");

        // Use backticks (`) so the selector is a valid template string
        const detailRows = document.querySelectorAll(`.month-details.month-${monthKey}`);

        if (detailRows.length === 0) return;

        button.addEventListener("click", () => {
            const isHidden = detailRows[0].classList.contains("d-none");

            detailRows.forEach(row => {
                row.classList.toggle("d-none");
            });

            button.textContent = isHidden ? "Collapse" : "Expand";
        });
    });

    // Toast + progress (%) + ETA updates
    const formUpdate = document.getElementById("updateSalesForm");
    const statusUrl = formUpdate && formUpdate.getAttribute("data-status-url");
    let isSubmitting = false;
    let progressInterval = null;

    function stopProgressPolling() {
        if (progressInterval) {
            clearInterval(progressInterval);
            progressInterval = null;
        }
    }

    function updateProgressToast() {
        if (!statusUrl) return;
        fetch(statusUrl, { headers: { "Accept": "application/json" } })
            .then(function (r) { return r.json(); })
            .then(function (st) {
                var toastMessage = document.getElementById("toast-message");
                if (!toastMessage) return;
                var pct = st.progress_percent != null ? Math.round(st.progress_percent) : 0;
                var eta = formatEta(st.eta_seconds);
                var loadingText = (window.JS_TRANSLATIONS && window.JS_TRANSLATIONS.loading) || "Loading: ";
                toastMessage.textContent = loadingText + pct + "%" + eta;
            })
            .catch(function () { });
    }

    function setTriggerButtonLoading(loading) {
        var btn = document.getElementById("triggerUpdateSalesBtn");
        if (!btn) return;
        var content = btn.querySelector(".btn-content");
        var loadingEl = btn.querySelector(".btn-loading");
        if (loading) {
            if (content) content.classList.add("d-none");
            if (loadingEl) loadingEl.classList.remove("d-none");
            btn.disabled = true;
        } else {
            if (content) content.classList.remove("d-none");
            if (loadingEl) loadingEl.classList.add("d-none");
            btn.disabled = false;
        }
    }

    function pollStatusAndCheckDone() {
        if (!statusUrl) return;
        fetch(statusUrl, { headers: { "Accept": "application/json" } })
            .then(function (r) { return r.json(); })
            .then(function (st) {
                var toastMessage = document.getElementById("toast-message");
                if (toastMessage) {
                    var pct = st.progress_percent != null ? Math.round(st.progress_percent) : 0;
                    var eta = formatEta(st.eta_seconds);
                    var loadingText = (window.JS_TRANSLATIONS && window.JS_TRANSLATIONS.loading) || "Loading: ";
                    toastMessage.textContent = loadingText + pct + "%" + eta;
                }
                if (!st.is_locked) {
                    stopProgressPolling();
                    setTriggerButtonLoading(false);
                    try { document.dispatchEvent(new CustomEvent("salesImportComplete")); } catch (e) { }
                    showToast((window.JS_TRANSLATIONS && window.JS_TRANSLATIONS.loadingCompleted) || "Loading completed");
                    setTimeout(function () { location.reload(); }, 1000);
                }
            })
            .catch(function () { });
    }

    function checkImportStatusOnLoad() {
        if (!statusUrl || !formUpdate) return;
        fetch(statusUrl, { headers: { "Accept": "application/json" } })
            .then(function (r) { return r.json(); })
            .then(function (st) {
                if (!st.is_locked) return;
                var startedAt = st.started_at ? new Date(st.started_at).getTime() : 0;
                var staleMs = 2 * 60 * 1000;
                if (startedAt && (Date.now() - startedAt > staleMs)) return;
                setTriggerButtonLoading(true);
                var pct = st.progress_percent != null ? Math.round(st.progress_percent) : 0;
                var eta = formatEta(st.eta_seconds);
                var loadingText = (window.JS_TRANSLATIONS && window.JS_TRANSLATIONS.loading) || "Loading: ";
                showToast(loadingText + pct + "%" + eta, "loading");
                stopProgressPolling();
                progressInterval = setInterval(pollStatusAndCheckDone, 1000);
            })
            .catch(function () { });
    }

    window.runSalesImport = function () {
        if (!formUpdate) return;
        if (isSubmitting) return;
        if (!confirm((window.JS_TRANSLATIONS && window.JS_TRANSLATIONS.importConfirm) || "Import new deals from CRM?")) return;

        isSubmitting = true;
        setTriggerButtonLoading(true);
        var button = formUpdate.querySelector("button[type=submit]");
        if (button) button.disabled = true;
        var loadingText = (window.JS_TRANSLATIONS && window.JS_TRANSLATIONS.loading) || "Loading: ";
        showToast(loadingText + "0%", "loading");
        stopProgressPolling();
        if (statusUrl) {
            progressInterval = setInterval(updateProgressToast, 1000);
        }

        var abortController = new AbortController();
        var timeoutId = setTimeout(function () {
            abortController.abort();
        }, 120000);

        fetch(formUpdate.action, {
            method: "POST",
            headers: {
                "X-CSRFToken": document.querySelector("[name=csrfmiddlewaretoken]").value,
                "Accept": "application/json",
            },
            signal: abortController.signal,
        })
            .then(function (response) {
                if (!response.ok) {
                    return response.text().then(function (text) {
                        showToast((window.JS_TRANSLATIONS && window.JS_TRANSLATIONS.error) || "Error", "error");
                        var networkErrText = (window.JS_TRANSLATIONS && window.JS_TRANSLATIONS.networkError) || "Network error: ";
                        throw new Error(networkErrText + text);
                    });
                }
                var contentType = response.headers.get("content-type") || "";
                if (!contentType.includes("application/json")) {
                    showToast((window.JS_TRANSLATIONS && window.JS_TRANSLATIONS.error) || "Error", "error");
                    var jsonErrText = (window.JS_TRANSLATIONS && window.JS_TRANSLATIONS.expectedJson) || "Expected JSON";
                    throw new Error(jsonErrText);
                }
                return response.json();
            })
            .then(function (data) {
                stopProgressPolling();
                if (data.success) {
                    showToast(data.message || (window.JS_TRANSLATIONS && window.JS_TRANSLATIONS.dataLoaded) || "Data loaded successfully!");
                    setTimeout(function () { location.reload(); }, 1000);
                } else {
                    showToast((window.JS_TRANSLATIONS && window.JS_TRANSLATIONS.error) || "Error", "error");
                    throw new Error(data.error || (window.JS_TRANSLATIONS && window.JS_TRANSLATIONS.error) || "Error");
                }
            })
            .catch(function (err) {
                console.error("Error:", err);
                stopProgressPolling();
                showToast((window.JS_TRANSLATIONS && window.JS_TRANSLATIONS.error) || "Error", "error");
            })
            .finally(function () {
                clearTimeout(timeoutId);
                isSubmitting = false;
                setTriggerButtonLoading(false);
                if (button) button.disabled = false;
                try {
                    document.dispatchEvent(new CustomEvent("salesImportComplete"));
                } catch (e) { }
            });
    };

    if (formUpdate) {
        formUpdate.addEventListener("submit", function (e) {
            e.preventDefault();
            window.runSalesImport();
        });
    }

    checkImportStatusOnLoad();
});

$(document).ready(function () {
    // Shared helper: render validation errors in modals
    function renderFormErrors(errors) {
        if (!errors || typeof errors !== 'object') return '';
        var html = '';
        for (var field in errors) {
            var first = errors[field][0];
            var msg = typeof first === 'string' ? first : (first && (first.message || first.msg)) || String(first);
            html += '<p class="text-danger">' + field + ': ' + msg + '</p>';
        }
        return html;
    }

    // --- Filter Logic ---
    function toggleFilterInputs() {
        if ($('#filter_month').is(':checked')) {
            $('#month_filter_group').show();
            $('#date_range_filter_group').hide();
        } else {
            $('#month_filter_group').hide();
            $('#date_range_filter_group').show();
        }
    }
    $('input[name="filter_type"]').on('change', toggleFilterInputs);
    toggleFilterInputs(); // Run on page load

    // --- Table Row Expansion ---
    $('.table-month-summary').on('click', function () {
        const row = $(this);
        const button = row.find('.toggle-btn');

        // Toggle the details row
        row.next('.month-details-wrapper').toggleClass('d-none');

        // Toggle the chevron icon and the row's expanded state
        button.toggleClass('expanded');
        row.toggleClass('expanded-row');
    });

    // --- In-memory Table Sorting ---
    $('.card').on('click', '.sortable-header', function () {
        const header = $(this);
        const table = header.closest('table');
        const tbody = table.find('tbody');
        const rows = tbody.find('tr').toArray();
        // Use .attr(): jQuery .data('sort-key') does not read data-sort-key (camelCase is sortKey).
        const sortKeyIndex = parseInt(header.attr('data-sort-key'), 10);
        const sortType = header.attr('data-sort-type') || 'string';
        if (Number.isNaN(sortKeyIndex)) {
            return;
        }

        let currentOrder = header.data('sort-order') || 'desc';
        let newOrder = currentOrder === 'asc' ? 'desc' : 'asc';

        // Reset other headers
        table.find('.sortable-header').not(header).each(function () {
            $(this).removeData('sort-order');
            $(this).removeClass('asc desc');
            $(this).find('.sort-icon').html('');
        });

        header.data('sort-order', newOrder);
        header.removeClass('asc desc').addClass(newOrder);

        const ascIcon = '<i class="bi bi-caret-up-fill"></i>';
        const descIcon = '<i class="bi bi-caret-down-fill"></i>';
        header.find('.sort-icon').html(newOrder === 'asc' ? ascIcon : descIcon);


        rows.sort(function (a, b) {
            const aVal = $(a).find('td').eq(sortKeyIndex).text().trim();
            const bVal = $(b).find('td').eq(sortKeyIndex).text().trim();

            let comparison = 0;
            if (sortType === 'number') {
                // Remove spaces, currency symbols, and convert comma to dot
                const aNum = parseFloat(aVal.replace(/\s/g, '').replace(/₴/g, '').replace(',', '.')) || 0;
                const bNum = parseFloat(bVal.replace(/\s/g, '').replace(/₴/g, '').replace(',', '.')) || 0;
                comparison = aNum - bNum;
            } else if (sortType === 'natural') {
                // CharField / CRM ids (may be "12345", "DEAL-12", "A1"/"A10"): numeric-aware string order
                comparison = aVal.localeCompare(bVal, 'ru', { numeric: true, sensitivity: 'base' });
            } else if (sortType === 'date') {
                const aDateParts = aVal.split('.');
                const bDateParts = bVal.split('.');
                const aDate = new Date(aDateParts[2], aDateParts[1] - 1, aDateParts[0]);
                const bDate = new Date(bDateParts[2], bDateParts[1] - 1, bDateParts[0]);
                comparison = aDate - bDate;
            } else { // string
                comparison = aVal.localeCompare(bVal, 'ru', { sensitivity: 'base' });
            }

            return newOrder === 'asc' ? comparison : -comparison;
        });

        tbody.empty().append(rows);
    });

    // --- Chart.js Initialization ---
    // Color palette from SCSS design
    // Purple — Sales
    const primaryAccent = 'rgba(108, 99, 255, 0.9)';   // #6c63ff — Sales
    const primaryAccentBorder = 'rgba(108, 99, 255, 1)';

    // Yellow — Salary
    const salaryColor = 'rgba(255, 212, 59, 0.9)';  // #ffd43b — Salary
    const salaryColorBorder = 'rgba(255, 212, 59, 1)';

    // Orange — Expenses
    const expensesColor = 'rgba(255, 106, 51, 0.9)';  // #ff6a33 — Expenses
    const expensesColorBorder = 'rgba(255, 106, 51, 1)';

    // Green — Profit
    const profitColor = 'rgba(76, 217, 100, 0.9)';  // #4cd964 — Profit
    const profitColorBorder = 'rgba(76, 217, 100, 1)';

    // Read colors from CSS variables for the active theme
    const root = document.documentElement;
    const chartGridColor = getComputedStyle(root).getPropertyValue('--chart-grid-color').trim() || 'rgba(228, 231, 238, 0.5)';
    const gridColor = chartGridColor;  // Use CSS variable for grid color
    const chartTextColor = getComputedStyle(root).getPropertyValue('--chart-text-color').trim() || '#2E2E3A';
    const chartAxisColor = getComputedStyle(root).getPropertyValue('--chart-axis-color').trim() || '#6F7381';

    // Initial datalabel color for current theme
    const initialTheme = root.getAttribute('data-theme') || 'dark';
    const datalabelInitialColor = initialTheme === 'light' ? '#1F2937' : '#ffffff';

    // Sequential palette for multiple categories (from SCSS design)
    const sequentialPalette = [
        'rgba(108, 99, 255, 0.9)',   // #6c63ff — purple (sales)
        'rgba(255, 212, 59, 0.9)',   // #ffd43b — yellow (salary)
        'rgba(255, 106, 51, 0.9)',   // #ff6a33 — orange (expenses)
        'rgba(76, 217, 100, 0.9)',   // #4cd964 — green (profit)
        'rgba(156, 39, 176, 0.9)',   // #9C27B0 — purple
        'rgba(186, 104, 200, 0.9)',  // #BA68C8 — light purple
        'rgba(255, 183, 77, 0.9)',   // #FFB74D — light orange
        'rgba(129, 199, 132, 0.9)',  // #81C784 — light green
        'rgba(255, 152, 0, 0.9)',    // #FF9800 — orange
        'rgba(76, 175, 80, 0.9)'     // #4CAF50 — green
    ];

    const borderColors = [
        'rgba(108, 99, 255, 1)',     // #6c63ff
        'rgba(255, 212, 59, 1)',     // #ffd43b
        'rgba(255, 106, 51, 1)',     // #ff6a33
        'rgba(76, 217, 100, 1)',     // #4cd964
        'rgba(156, 39, 176, 1)',     // #9C27B0
        'rgba(186, 104, 200, 1)',     // #BA68C8
        'rgba(255, 183, 77, 1)',     // #FFB74D
        'rgba(129, 199, 132, 1)',    // #81C784
        'rgba(255, 152, 0, 1)',      // #FF9800
        'rgba(76, 175, 80, 1)'       // #4CAF50
    ];

    // Show every month label on X (mobile and desktop); rotate if needed
    const isMobileChart = typeof window !== 'undefined' && window.matchMedia('(max-width: 768px)').matches;
    const xTicksOptions = {
        color: chartAxisColor,
        font: { size: isMobileChart ? 10 : 12 },
        maxRotation: 65,
        minRotation: 0,   // Chart.js rotates labels up to 65° when space is tight
        autoSkip: false,  // show all months
        maxTicksLimit: undefined
    };

    // Chart options with modern styling
    const chartOptions = {
        responsive: true,
        maintainAspectRatio: false,
        interaction: {
            intersect: false,
            mode: 'index'
        },
        animation: {
            duration: 800, // Initial load animation duration
            easing: 'easeOutQuart' // Smooth easing
        },
        scales: {
            y: {
                beginAtZero: true,
                grid: {
                    color: gridColor, // from gridColor
                    lineWidth: 1,
                    drawBorder: false
                },
                ticks: {
                    color: chartAxisColor, // axis tick color from CSS variable
                    font: {
                        size: 12 // 12px axis ticks
                    }
                }
            },
            x: {
                grid: {
                    display: false
                },
                ticks: xTicksOptions
            }
        },
        plugins: {
            datalabels: {
                display: false,
            },
            legend: {
                display: true,
                position: 'bottom',
                labels: {
                    padding: 15,
                    usePointStyle: true,
                    pointStyle: 'circle',
                    font: {
                        size: 12 // 12px legend
                    },
                    color: chartTextColor // legend text from CSS variable
                },
                onClick: function (e, legendItem) {
                    const index = legendItem.datasetIndex;
                    const chart = this.chart;
                    const meta = chart.getDatasetMeta(index);

                    meta.hidden = meta.hidden === null ? !chart.data.datasets[index].hidden : null;
                    chart.update();
                }
            },
            tooltip: {
                backgroundColor: 'rgba(0, 0, 0, 0.8)',
                padding: 12,
                titleFont: {
                    size: 14, // 14px tooltip title
                    weight: '600' // SemiBold
                },
                bodyFont: {
                    size: 12 // 12px tooltip body
                },
                borderColor: 'rgba(255, 255, 255, 0.1)',
                borderWidth: 1,
                cornerRadius: 8,
                displayColors: true,
                callbacks: {
                    label: function (context) {
                        let label = context.dataset.label || '';
                        if (label) {
                            label += ': ';
                        }
                        if (context.parsed.y !== null) {
                            const value = context.parsed.y;
                            const formatted = value.toLocaleString('ru-RU', {
                                minimumFractionDigits: 0,
                                maximumFractionDigits: 0
                            });
                            label += formatted + ' ₴';
                        }
                        return label;
                    }
                }
            }
        }
    };

    // Manager charts: one bar per hover (point mode)
    const managerChartOptions = {
        ...chartOptions,
        interaction: {
            intersect: false,
            mode: 'point' // one series point, not all managers for the month
        }
    };

    // Shared Pie Chart Options
    const commonPieChartOptions = {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
            legend: {
                display: true,
                position: 'bottom',
                labels: {
                    padding: 15,
                    usePointStyle: true,
                    pointStyle: 'circle',
                    pointBorderWidth: 0, // no white border on legend points
                    font: {
                        size: 12
                    },
                    color: chartTextColor // legend text from CSS variable
                }
            },
            tooltip: {
                backgroundColor: 'rgba(0, 0, 0, 0.8)',
                padding: 12,
                titleFont: {
                    size: 13,
                    weight: 'bold'
                },
                bodyFont: {
                    size: 12
                },
                borderColor: 'rgba(255, 255, 255, 0.1)',
                borderWidth: 1,
                cornerRadius: 8,
                callbacks: {
                    label: function (context) {
                        const label = context.label || '';
                        const value = context.parsed;
                        const total = context.dataset.data.reduce((a, b) => a + b, 0);
                        const percentage = ((value / total) * 100).toFixed(1);
                        const formatted = value.toLocaleString('ru-RU', {
                            minimumFractionDigits: 0,
                            maximumFractionDigits: 0
                        });
                        return label + ': ' + formatted + ' ₴ (' + percentage + '%)';
                    }
                }
            },
            datalabels: {
                display: true,
                formatter: (value, ctx) => {
                    const datapoints = ctx.chart.data.datasets[0].data
                    const total = datapoints.reduce((total, datapoint) => total + datapoint, 0)
                    const percentage = value / total * 100
                    return percentage.toFixed(1) + '%'
                },
                color: datalabelInitialColor,
                font: {
                    weight: 'bold',
                    size: 11
                }
            }
        }
    };

    if (typeof Chart !== 'undefined') {
        try {
            if (typeof ChartDataLabels !== 'undefined') {
                Chart.register(ChartDataLabels);
            }

            // Chart 1: Sales & Salary - Purple for Sales, Mint for Salary
        const chartDataEl = document.getElementById('chart-data');
        if (chartDataEl) {
            const chartData = JSON.parse(chartDataEl.textContent);
            const ctx = document.getElementById('salesSalaryChart').getContext('2d');
            const chartLabelSales = (window.CHART_LABELS && window.CHART_LABELS.sales) || 'Sales';
            const chartLabelSalary = (window.CHART_LABELS && window.CHART_LABELS.salary) || 'Salary';
            window.salesChart = new Chart(ctx, {
                type: 'bar',
                data: {
                    labels: chartData.labels,
                    datasets: [{
                        label: chartLabelSales,
                        data: chartData.sales,
                        backgroundColor: primaryAccent, // #6c63ff — purple
                        borderColor: primaryAccentBorder,
                        borderWidth: 1.5,
                        borderRadius: 6 // rounded bar corners
                    }, {
                        label: chartLabelSalary,
                        data: chartData.salaries,
                        backgroundColor: salaryColor, // #ffd43b — yellow
                        borderColor: salaryColorBorder,
                        borderWidth: 1.5,
                        borderRadius: 6 // rounded bar corners
                    }]
                },
                options: managerChartOptions
            });
        }

        // Chart 2 & 3: Manager Sales (Bar & Pie)
        const managerChartDataEl = document.getElementById('chart-data-by-manager');
        if (managerChartDataEl) {
            const managerChartData = JSON.parse(managerChartDataEl.textContent);
            const managerCtx = document.getElementById('managerSalesChart').getContext('2d');
            managerChartData.datasets.forEach((dataset, index) => {
                dataset.backgroundColor = sequentialPalette[index % sequentialPalette.length];
                dataset.borderColor = borderColors[index % borderColors.length];
                dataset.borderWidth = 1.5;
                dataset.borderRadius = 6; // rounded bar corners
            });
            window.managerChart = new Chart(managerCtx, { type: 'bar', data: managerChartData, options: managerChartOptions });

            const managerSalesPieData = JSON.parse(managerChartDataEl.textContent);
            const managerSalesPieCtx = document.getElementById('managerSalesPieChart').getContext('2d');

            const pieLabels = [];
            const pieValues = [];

            managerSalesPieData.datasets.forEach(dataset => {
                pieLabels.push(dataset.label);
                pieValues.push(dataset.data.reduce((a, b) => a + b, 0));
            });

            window.managerSalesPieChart = new Chart(managerSalesPieCtx, {
                type: 'pie',
                data: {
                    labels: pieLabels,
                    datasets: [{
                        data: pieValues,
                        backgroundColor: sequentialPalette.slice(0, pieValues.length),
                        borderWidth: 0
                    }]
                },
                options: commonPieChartOptions
            });

            $('input[name="manager_chart_type"]').on('change', function () {
                if ($(this).val() === 'bar') {
                    $('#managerPieChartContainer').addClass('d-none');
                    $('#managerBarChartContainer').removeClass('d-none');
                } else {
                    $('#managerBarChartContainer').addClass('d-none');
                    $('#managerPieChartContainer').removeClass('d-none');
                    managerSalesPieChart.resize();
                }
                // Sync active class on labels
                $('input[name="manager_chart_type"]').each(function () {
                    if ($(this).is(':checked')) {
                        $(this).next('label').addClass('active');
                    } else {
                        $(this).next('label').removeClass('active');
                    }
                });
            });
        }

        // Chart 4: Expense by Month - Golden for expenses
        const expenseChartDataEl = document.getElementById('expense-chart-data');
        if (expenseChartDataEl) {
            const expenseChartData = JSON.parse(expenseChartDataEl.textContent);
            const expenseCtx = document.getElementById('expenseMonthChart').getContext('2d');
            const chartLabelExpenses = (window.CHART_LABELS && window.CHART_LABELS.expenses) || 'Expenses';
            window.expenseMonthChart = new Chart(expenseCtx, {
                type: 'bar',
                data: {
                    labels: expenseChartData.labels,
                    datasets: [{
                        label: chartLabelExpenses,
                        data: expenseChartData.data,
                        backgroundColor: expensesColor, // #ff6a33 — orange
                        borderColor: expensesColorBorder,
                        borderWidth: 1.5,
                        borderRadius: 6 // rounded bar corners
                    }]
                },
                options: chartOptions
            });
        }

        // Chart 5 & 6: Expense by Type (Bar & Pie)
        const expenseTypeChartDataEl = document.getElementById('expense-type-chart-data');
        if (expenseTypeChartDataEl) {
            const expenseTypeChartData = JSON.parse(expenseTypeChartDataEl.textContent);
            const expenseTypeCtx = document.getElementById('expenseTypeChart').getContext('2d');
            expenseTypeChartData.datasets.forEach((dataset, index) => {
                dataset.backgroundColor = sequentialPalette[index % sequentialPalette.length];
                dataset.borderColor = borderColors[index % borderColors.length];
                dataset.borderWidth = 1.5;
                dataset.borderRadius = 6; // rounded bar corners
            });
            window.expenseTypeChart = new Chart(expenseTypeCtx, {
                type: 'bar',
                data: expenseTypeChartData,
                options: managerChartOptions
            });

            const expenseTypePieData = JSON.parse(expenseTypeChartDataEl.textContent);
            const expenseTypePieCtx = document.getElementById('expenseTypePieChart').getContext('2d');

            const expensePieLabels = [];
            const expensePieValues = [];

            expenseTypePieData.datasets.forEach(dataset => {
                expensePieLabels.push(dataset.label);
                expensePieValues.push(dataset.data.reduce((a, b) => a + b, 0));
            });

            window.expenseTypePieChart = new Chart(expenseTypePieCtx, {
                type: 'pie',
                data: {
                    labels: expensePieLabels,
                    datasets: [{
                        data: expensePieValues,
                        backgroundColor: sequentialPalette.slice(0, expensePieValues.length),
                        borderWidth: 0
                    }]
                },
                options: commonPieChartOptions
            });

            $('input[name="expense_type_chart_type"]').on('change', function () {
                if ($(this).val() === 'bar') {
                    $('#expenseTypePieChartContainer').addClass('d-none');
                    $('#expenseTypeBarChartContainer').removeClass('d-none');
                } else {
                    $('#expenseTypeBarChartContainer').addClass('d-none');
                    $('#expenseTypePieChartContainer').removeClass('d-none');
                    expenseTypePieChart.resize();
                }
                // Sync active class on labels
                $('input[name="expense_type_chart_type"]').each(function () {
                    if ($(this).is(':checked')) {
                        $(this).next('label').addClass('active');
                    } else {
                        $(this).next('label').removeClass('active');
                    }
                });
            });
        }

        // Chart 7 & 8: Salary by Manager (Bar & Pie)
        const salaryManagerMonthChartDataEl = document.getElementById('salary-chart-data-by-manager');
        if (salaryManagerMonthChartDataEl) {
            const salaryManagerMonthChartData = JSON.parse(salaryManagerMonthChartDataEl.textContent);
            const salaryManagerMonthCtx = document.getElementById('salaryManagerMonthChart').getContext('2d');
            salaryManagerMonthChartData.datasets.forEach((dataset, index) => {
                dataset.backgroundColor = sequentialPalette[index % sequentialPalette.length];
                dataset.borderColor = borderColors[index % borderColors.length];
                dataset.borderWidth = 1.5;
                dataset.borderRadius = 6; // rounded bar corners
            });
            window.salaryManagerMonthChart = new Chart(salaryManagerMonthCtx, { type: 'bar', data: salaryManagerMonthChartData, options: managerChartOptions });

            const salaryManagerPieData = JSON.parse(salaryManagerMonthChartDataEl.textContent);
            const salaryManagerPieCtx = document.getElementById('salaryManagerPieChart').getContext('2d');

            const salaryPieLabels = [];
            const salaryPieValues = [];

            salaryManagerPieData.datasets.forEach(dataset => {
                salaryPieLabels.push(dataset.label);
                salaryPieValues.push(dataset.data.reduce((a, b) => a + b, 0));
            });

            window.salaryManagerPieChart = new Chart(salaryManagerPieCtx, {
                type: 'pie',
                data: {
                    labels: salaryPieLabels,
                    datasets: [{
                        data: salaryPieValues,
                        backgroundColor: sequentialPalette.slice(0, salaryPieValues.length),
                        borderWidth: 0
                    }]
                },
                options: commonPieChartOptions
            });

            $('input[name="salary_chart_type"]').on('change', function () {
                if ($(this).val() === 'bar') {
                    $('#salaryPieChartContainer').addClass('d-none');
                    $('#salaryBarChartContainer').removeClass('d-none');
                } else {
                    $('#salaryBarChartContainer').addClass('d-none');
                    $('#salaryPieChartContainer').removeClass('d-none');
                    salaryManagerPieChart.resize();
                }
                // Sync active class on labels
                $('input[name="salary_chart_type"]').each(function () {
                    if ($(this).is(':checked')) {
                        $(this).next('label').addClass('active');
                    } else {
                        $(this).next('label').removeClass('active');
                    }
                });
            });
        }

        } catch (e) {
            console.error("Chart initialization error:", e);
        }
    }

    // Resize charts when switching tabs
    window.resizeAllCharts = function () {
        var charts = [
            window.salesChart,
            window.managerChart,
            window.managerSalesPieChart,
            window.expenseMonthChart,
            window.expenseTypeChart,
            window.expenseTypePieChart,
            window.salaryManagerMonthChart,
            window.salaryManagerPieChart
        ];
        charts.forEach(function (chart) {
            if (chart) chart.resize();
        });
    };

    $('button[data-bs-toggle="pill"]').on('shown.bs.tab', function (e) {
        // Resize all charts when window is resized
        const resizeCharts = window.resizeAllCharts;

        // Add resize event listener with debounce
        let resizeTimeout;
        window.addEventListener('resize', () => {
            clearTimeout(resizeTimeout);
            resizeTimeout = setTimeout(() => {
                resizeCharts();
            }, 100);
        });

        // Also resize when switching tabs
        $('button[data-bs-toggle="pill"]').on('shown.bs.tab', function () {
            setTimeout(resizeCharts, 100);
        });

        resizeCharts();
    });

    $(window).on('load', function () {
        window.dispatchEvent(new Event('resize'));
    });

    // Refresh all charts when theme changes
    function updateChartsTheme() {
        // Read updated colors from CSS variables
        const root = document.documentElement;
        const newTheme = root.getAttribute('data-theme') || 'dark';
        const chartGridColor = getComputedStyle(root).getPropertyValue('--chart-grid-color').trim();
        const chartTextColor = getComputedStyle(root).getPropertyValue('--chart-text-color').trim();
        const chartAxisColor = getComputedStyle(root).getPropertyValue('--chart-axis-color').trim();
        const datalabelColor = newTheme === 'light' ? '#1F2937' : '#ffffff';

        const chartsToUpdate = [
            window.salesChart,
            window.managerChart,
            window.managerSalesPieChart,
            window.expenseMonthChart,
            window.expenseTypeChart,
            window.expenseTypePieChart,
            window.salaryManagerMonthChart,
            window.salaryManagerPieChart
        ];

        chartsToUpdate.forEach(chart => {
            if (!chart) return;

            // Update axis/grid colors per chart
            if (chart.options.scales) {
                ['x', 'y'].forEach(axis => {
                    if (chart.options.scales[axis]) {
                        if (chart.options.scales[axis].ticks) {
                            chart.options.scales[axis].ticks.color = chartAxisColor;
                        }
                        if (chart.options.scales[axis].grid) {
                            chart.options.scales[axis].grid.color = chartGridColor;
                        }
                    }
                });
            }

            // Update legend color
            if (chart.options.plugins && chart.options.plugins.legend && chart.options.plugins.legend.labels) {
                chart.options.plugins.legend.labels.color = chartTextColor;
            }

            // Update pie datalabel colors
            if (chart.config.type === 'pie' && chart.options.plugins.datalabels) {
                chart.options.plugins.datalabels.color = datalabelColor;
            }

            chart.update();
        });
    }

    // themeChanged: refresh charts
    document.addEventListener('themeChanged', function () {
        updateChartsTheme();
    });

    // Filter toggle buttons - update active state
    $('.filter-toggle-input').on('change', function () {
        $('.filter-toggle-btn').removeClass('active');
        $(this).next('.filter-toggle-btn').addClass('active');
    });

    // Loading indicators for filter form
    $('#filterForm').on('submit', function () {
        const btn = $('#applyFilterBtn');
        const btnContent = btn.find('.btn-content');
        const btnLoading = btn.find('.btn-loading');

        if (btnContent.length && btnLoading.length) {
            btnContent.addClass('d-none');
            btnLoading.removeClass('d-none');
            btn.prop('disabled', true);
        }
    });

    // Loading indicator for update sales button
    $('#updateSalesForm').on('submit', function () {
        const btn = $('#updateSalesBtn');
        const btnContent = btn.find('.btn-content');
        const btnLoading = btn.find('.btn-loading');

        if (btnContent.length && btnLoading.length) {
            btnContent.addClass('d-none');
            btnLoading.removeClass('d-none');
            btn.prop('disabled', true);
        }
    });

    // Modal handling for production expenses
    const expenseModalEl = document.getElementById('expenseModal');
    if (expenseModalEl) {
        const expenseModal = new bootstrap.Modal(expenseModalEl);
        const addExpenseTitle = expenseModalEl.dataset.addTitle || 'Add expense';
        const editExpenseTitle = expenseModalEl.dataset.editTitle || 'Edit expense';

        expenseModalEl.addEventListener('hide.bs.modal', function (event) {
            const active = document.activeElement;
            if (this.contains(active)) {
                try {
                    active.blur();
                } catch (e) {
                    console.error('Failed to blur active element', e);
                }
            }
        });

        const childModalEl = document.getElementById('childModal');
        let childModal = null;
        if (childModalEl) {
            childModal = new bootstrap.Modal(childModalEl);
        }



        $('#addExpenseBtn').on('click', function () {
            const url = $(this).data('url');
            $.ajax({
                url: url,
                success: function (data) {
                    $('#expenseModal .modal-body').html(data);
                    $('#expenseModalLabel').text(addExpenseTitle);
                }
            });
        });

        $('.edit-expense-btn').on('click', function () {
            const url = $(this).data('url');
            $.ajax({
                url: url,
                success: function (data) {
                    $('#expenseModal .modal-body').html(data);
                    $('#expenseModalLabel').text(editExpenseTitle);
                }
            });
        });

        $(document).on('submit', '#expenseModal form', function (e) {
            e.preventDefault();
            $.ajax({
                type: 'POST',
                url: $(this).attr('action'),
                data: $(this).serialize(),
                success: function (data) {
                    if (data.success) {
                        expenseModal.hide();
                        location.reload();
                    } else {
                        $('#expenseModal .modal-body').prepend(renderFormErrors(data.errors));
                    }
                }
            });
        });

        $(document).on('click', '.open-child-modal', function (e) {
            e.preventDefault();
            const url = $(this).attr('href');
            const title = $(this).data('modal-title');

            $('#childModalLabel').text(title);
            $.ajax({
                url: url,
                success: function (data) {
                    $('#childModal .modal-body').html(data);
                    if (childModal) {
                        childModal.show();
                    }
                }
            });
        });

        $(document).on('submit', '#childModal .child-form', function (e) {
            e.preventDefault();
            $.ajax({
                type: 'POST',
                url: $(this).attr('action'),
                data: $(this).serialize(),
                success: function (data) {
                    if (data.success) {
                        // Blur any focused element inside the child modal before hiding
                        const childEl = document.getElementById('childModal');
                        const active = document.activeElement;
                        if (childEl && active && childEl.contains(active)) {
                            try { active.blur(); } catch (e) { }
                        }
                        if (childModal) {
                            childModal.hide();
                        }
                        // Update the select field in the parent modal
                        if ($(this).attr('action').includes('employee')) {
                            $('#id_employee').append(new Option(data.name, data.id, true, true));
                        } else if ($(this).attr('action').includes('expense_type')) {
                            $('#id_expense_type').append(new Option(data.name, data.id, true, true));
                        }
                    } else {
                        $('#childModal .modal-body').prepend(renderFormErrors(data.errors));
                    }
                }
            });
        });
    }

    const salaryModalEl = document.getElementById('salaryModal');
    if (salaryModalEl) {
        const salaryModal = new bootstrap.Modal(salaryModalEl);
        const addPaymentTitle = salaryModalEl.dataset.addTitle || 'Add payment';
        const editPaymentTitle = salaryModalEl.dataset.editTitle || 'Edit payment';

        salaryModalEl.addEventListener('hide.bs.modal', function (event) {
            const active = document.activeElement;
            if (this.contains(active)) {
                try {
                    active.blur();
                } catch (e) {
                    console.error('Failed to blur active element', e);
                }
            }
        });

        salaryModalEl.addEventListener('hidden.bs.modal', function (event) {
            // Check if the reload is needed, e.g., by setting a flag
            if (this.dataset.needsReload) {
                location.reload();
                delete this.dataset.needsReload;
            }
        });

        $('#addSalaryPaymentBtn').on('click', function () {
            const url = $(this).data('url');
            $.ajax({
                url: url,
                success: function (data) {
                    $('#salaryModal .modal-body').html(data);
                    $('#salaryModalLabel').text(addPaymentTitle);
                }
            });
        });

        $('.edit-salary-payment-btn').on('click', function () {
            const url = $(this).data('url');
            $.ajax({
                url: url,
                success: function (data) {
                    $('#salaryModal .modal-body').html(data);
                    $('#salaryModalLabel').text(editPaymentTitle);
                    $('#salaryModal #id_manager').trigger('change');
                }
            });
        });

        $(document).on('submit', '#salaryModal form', function (e) {
            e.preventDefault();
            const form = $(this);
            const amountInput = form.find('input[name="amount"]');
            const originalValue = amountInput.val();
            amountInput.val(originalValue.replace(/\s/g, '').replace(',', '.'));

            $.ajax({
                type: 'POST',
                url: form.attr('action'),
                data: form.serialize(),
                success: function (data) {
                    if (data.success) {
                        salaryModalEl.dataset.needsReload = true;

                        salaryModal.hide();
                    } else {
                        $('#salaryModal .modal-body').prepend(renderFormErrors(data.errors));
                    }
                },
                complete: function () {
                    amountInput.val(originalValue);
                }
            });
        });
    }

    $(document).on('click', '.print-expense-btn', function () {
        const printButton = $(this);
        if (printButton.is(':disabled')) {
            return;
        }

        try {
            printButton.prop('disabled', true);

            const employee = printButton.data('employee');
            const expenseType = printButton.data('expense-type');
            const date = printButton.data('date');
            const amount = printButton.data('amount');
            const comment = printButton.data('comment');

            // Fill print template
            $('#printExpenseEmployee').text(employee);
            $('#printExpenseType').text(expenseType);
            $('#printExpenseDate').text(date);
            $('#printExpenseAmount').text(amount + ' ₴');

            const commentRow = $('#printExpenseCommentRow');
            const commentValue = $('#printExpenseComment');

            if (comment && String(comment).trim() !== '') {
                commentRow.css('display', 'flex');
                commentValue.html(comment);
            } else {
                commentRow.hide();
                commentValue.html('');
            }

            printWithIframe($('#printExpenseArea').html());

        } catch (e) {
            console.error("Error preparing for print:", e);
            alert("An error occurred while preparing the document for printing.");
        } finally {
            // Always re-enable the button on failure
            printButton.prop('disabled', false);
        }
    });

    // Fetch and display remaining salary
    $(document).on('change', '#salaryModal #id_manager', function () {
        var managerId = $(this).val();
        if (managerId) {
            $.ajax({
                url: '/get-remaining-salary/',
                data: {
                    'manager_id': managerId
                },
                dataType: 'json',
                success: function (data) {
                    var remainingSalary = parseFloat(data.remaining_salary);
                    if (data.remaining_salary && !isNaN(remainingSalary)) {
                        var formattedSalary = new Intl.NumberFormat('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(remainingSalary);
                        $('#remaining_salary').val(formattedSalary);
                    } else {
                        $('#remaining_salary').val('0,00');
                    }
                },
                error: function () {
                    $('#remaining_salary').val('0,00');
                }
            });
        } else {
            $('#remaining_salary').val('0,00');
        }
    });

    // Salary amount: allow only digits + one decimal separator.
    $(document).on('input', '#salaryModal input[name="amount"]', function () {
        $(this).val(formatAmountInputValue($(this).val(), 2));
    });

    // --- Users list: registration modal (moved from users_list.html) ---
    var registerModalEl = document.getElementById('registerModal');
    if (registerModalEl) {
        var registerModal = new bootstrap.Modal(registerModalEl);
        var triggerElement = null;
        $('.open-register-modal').on('click', function (e) {
            e.preventDefault();
            triggerElement = this;
            var url = $(this).attr('href');
            $.ajax({
                url: url,
                success: function (data) {
                    $('#registerModal .modal-body').html(data);
                    registerModal.show();
                }
            });
        });
        $(document).on('submit', '#registerModal .register-form', function (e) {
            e.preventDefault();
            $.ajax({
                type: 'POST',
                url: $(this).attr('action'),
                data: $(this).serialize(),
                success: function (data) {
                    if (data.success) {
                        registerModal.hide();
                    } else {
                        var error_html = '<div class="alert alert-danger">';
                        if (typeof data.errors === 'object' && data.errors !== null) {
                            for (var field in data.errors) {
                                error_html += '<p class="mb-1">' + field + ': ' + data.errors[field].join(', ') + '</p>';
                            }
                        } else {
                            error_html += '<p>An unknown error occurred.</p>';
                        }
                        error_html += '</div>';
                        $('#registerModal .modal-body').prepend(error_html);
                    }
                }
            });
        });
        registerModalEl.addEventListener('hidden.bs.modal', function () {
            if (triggerElement) triggerElement.focus();
            location.reload();
        });
    }

    // --- Home (sales_list): "Refresh sales" button (moved from sales_list.html) ---
    // "Loading..." is set only inside runSalesImport() after confirm;
    // do not toggle on click or Cancel leaves the button stuck loading.
    var triggerUpdateSalesBtn = document.getElementById('triggerUpdateSalesBtn');
    if (triggerUpdateSalesBtn) {
        $('#triggerUpdateSalesBtn').on('click', function () {
            if (typeof window.runSalesImport === 'function') {
                window.runSalesImport();
            } else {
                $('#updateSalesForm').submit();
            }
        });
        document.addEventListener('salesImportComplete', function () {
            var triggerBtn = $('#triggerUpdateSalesBtn');
            triggerBtn.find('.btn-content').removeClass('d-none');
            triggerBtn.find('.btn-loading').addClass('d-none');
            triggerBtn.prop('disabled', false);
        });
    }

    // --- AI Analysis: ChatGPT Status Check ---
    const ai = window.AI_CHAT_I18N || {};
    const aiT = (k, fb) => {
        const v = ai[k];
        return (v !== undefined && v !== '') ? v : fb;
    };
    const modelStatusEl = document.getElementById('model-status');
    const statusIndicatorEl = document.getElementById('status-indicator');
    const modelInfoEl = document.getElementById('model-info');
    const modelNameEl = document.getElementById('model-name');

    if (modelStatusEl) {
        function checkChatGPTStatus() {
            fetch('/api/ai/status/', {
                method: 'GET',
                headers: {
                    'Accept': 'application/json',
                }
            })
                .then(response => response.json())
                .then(data => {
                    if (data.status === 'ready') {
                        modelStatusEl.textContent = aiT('ready', 'Ready');
                        modelStatusEl.style.color = '#4cd964'; // green
                        if (statusIndicatorEl) {
                            statusIndicatorEl.style.backgroundColor = '#4cd964';
                        }
                        if (data.model_name && modelNameEl) {
                            modelNameEl.textContent = data.model_name;
                            if (modelInfoEl) modelInfoEl.style.display = 'block';
                        }
                    } else if (data.status === 'loading') {
                        modelStatusEl.textContent = aiT('loading', 'Loading...');
                        modelStatusEl.style.color = '#ffa500'; // orange
                        if (statusIndicatorEl) {
                            statusIndicatorEl.style.backgroundColor = '#ffa500';
                        }
                    } else if (data.status === 'not_configured') {
                        modelStatusEl.textContent = aiT('notConfigured', 'Not configured');
                        modelStatusEl.style.color = '#ff4d4d'; // red
                        if (statusIndicatorEl) {
                            statusIndicatorEl.style.backgroundColor = '#ff4d4d';
                        }
                    } else if (data.status === 'error') {
                        modelStatusEl.textContent = aiT('errorPrefix', 'Error:') + ' ' + (data.message || aiT('unknownError', 'Unknown error'));
                        modelStatusEl.style.color = '#ff4d4d'; // red
                        if (statusIndicatorEl) {
                            statusIndicatorEl.style.backgroundColor = '#ff4d4d';
                        }
                    } else {
                        modelStatusEl.textContent = aiT('unknownStatus', 'Unknown status');
                        modelStatusEl.style.color = '#ffa500';
                        if (statusIndicatorEl) {
                            statusIndicatorEl.style.backgroundColor = '#ffa500';
                        }
                    }
                })
                .catch(error => {
                    console.error('Error checking ChatGPT status:', error);
                    modelStatusEl.textContent = aiT('connectionError', 'Connection error');
                    modelStatusEl.style.color = '#ff4d4d';
                    if (statusIndicatorEl) {
                        statusIndicatorEl.style.backgroundColor = '#ff4d4d';
                    }
                });
        }

        // Initial status check
        checkChatGPTStatus();

        // Poll status every 30s
        setInterval(checkChatGPTStatus, 30000);
    }

    // --- AI Analysis: Analyze Button Handler ---
    const analyzeBtn = document.getElementById('analyze-btn');
    const clearBtn = document.getElementById('clear-btn');
    const analysisQuestion = document.getElementById('analysis-question');
    const tokenUsage = document.getElementById('token-usage');
    const tokenInfoText = document.getElementById('token-info-text');
    const dataCardsContainer = document.getElementById('data-cards-container');
    const chartResult = document.getElementById('chart-result');
    const tableResult = document.getElementById('table-result');
    const searchSection = document.getElementById('search-section');
    const chatMessages = document.getElementById('chat-messages');

    // Chat message management
    let currentAssistantMessage = null;
    let currentLoadingMessage = null;
    let currentHistoryId = null;

    function addUserMessage(text) {
        if (!chatMessages) return;
        const messageDiv = document.createElement('div');
        messageDiv.className = 'ai-chat-message user';
        messageDiv.innerHTML = `
            <div class="ai-chat-message-content">${escapeHtml(text)}</div>
            <div class="ai-chat-message-avatar">${escapeHtml(aiT('userLabel', 'You'))}</div>
        `;
        chatMessages.appendChild(messageDiv);
        scrollToBottom();
        return messageDiv;
    }

    /** Add assistant message. insertAboveLast=true inserts above the last bubble (above the user question). */
    function addAssistantMessage(insertAboveLast) {
        if (!chatMessages) return null;
        const messageDiv = document.createElement('div');
        messageDiv.className = 'ai-chat-message assistant';
        messageDiv.innerHTML = `
            <div class="ai-chat-message-avatar">AI</div>
            <div class="ai-chat-message-content"></div>
        `;
        if (insertAboveLast && chatMessages.lastChild) {
            chatMessages.insertBefore(messageDiv, chatMessages.lastChild);
        } else {
            chatMessages.appendChild(messageDiv);
        }
        scrollToBottom();
        return messageDiv;
    }

    /** insertAboveLast=true: loading spinner above last message (above the question). */
    function addLoadingMessage(insertAboveLast) {
        if (!chatMessages) return null;
        if (currentLoadingMessage) {
            return currentLoadingMessage;
        }
        const messageDiv = document.createElement('div');
        messageDiv.className = 'ai-chat-message assistant';
        messageDiv.innerHTML = `
            <div class="ai-chat-message-avatar">AI</div>
            <div class="ai-chat-message-loading">
                <div class="spinner-border text-primary" role="status" style="width: 1rem; height: 1rem; border-width: 2px;">
                    <span class="visually-hidden">${escapeHtml(aiT('loadingAria', 'Loading...'))}</span>
                </div>
                <span>${escapeHtml(aiT('analyzing', 'Analysis in progress...'))}</span>
            </div>
        `;
        if (insertAboveLast && chatMessages.lastChild) {
            chatMessages.insertBefore(messageDiv, chatMessages.lastChild);
        } else {
            chatMessages.appendChild(messageDiv);
        }
        currentLoadingMessage = messageDiv;
        scrollToBottom();
        return messageDiv;
    }

    function removeLoadingMessage() {
        if (currentLoadingMessage) {
            currentLoadingMessage.remove();
            currentLoadingMessage = null;
        }
    }

    function scrollToBottom() {
        if (chatMessages) {
            chatMessages.scrollTop = chatMessages.scrollHeight;
        }
    }

    function escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    /** Escape prose, turn **bold** into <strong> (safe: only escaped segments are emitted). */
    function formatAiAssistantProse(text) {
        if (!text) return '';
        const re = /\*\*([\s\S]*?)\*\*/g;
        let lastIndex = 0;
        let out = '';
        let m;
        while ((m = re.exec(text)) !== null) {
            out += escapeHtml(text.slice(lastIndex, m.index));
            out += '<strong>' + escapeHtml(m[1]) + '</strong>';
            lastIndex = m.index + m[0].length;
        }
        out += escapeHtml(text.slice(lastIndex));
        return out;
    }

    function clearChat() {
        if (chatMessages) {
            chatMessages.innerHTML = '';
        }
        currentAssistantMessage = null;
        currentLoadingMessage = null;
        currentHistoryId = null;
        if (dataCardsContainer) {
            dataCardsContainer.style.display = 'none';
        }
        if (tableResult) {
            tableResult.style.display = 'none';
        }
        if (chartResult) {
            chartResult.style.display = 'none';
        }
        if (clearBtn) {
            clearBtn.classList.add('d-none');
        }
        if (tokenUsage) {
            tokenUsage.classList.add('d-none');
        }
    }

    /** Build conversation history for continuation. excludeLast=true skips the last message (current question). */
    function getConversationHistory(excludeLast) {
        if (!chatMessages) return [];
        const messages = chatMessages.querySelectorAll('.ai-chat-message:not(.ai-chat-message-loading)');
        const list = [];
        const limit = excludeLast ? messages.length - 1 : messages.length;
        for (let i = 0; i < limit; i++) {
            const msg = messages[i];
            const contentEl = msg.querySelector('.ai-chat-message-content');
            if (!contentEl) continue;

            // Clone and strip tables before reading text (avoid raw table text)
            const clone = contentEl.cloneNode(true);
            const tables = clone.querySelectorAll('table');
            tables.forEach(t => t.remove());

            const content = clone.textContent.trim();

            let tableDataStr = msg.dataset.tableData;
            let tableData = undefined;
            if (tableDataStr) {
                try {
                    tableData = JSON.parse(tableDataStr);
                } catch (e) { }
            }

            const role = msg.classList.contains('user') ? 'user' : 'assistant';

            // Prefer raw assistant text from dataset if set
            let finalContent = content;
            if (role === 'assistant' && msg.dataset.rawContent) {
                finalContent = msg.dataset.rawContent;
            }

            if (!finalContent && !tableData) continue;

            const msgObj = { role: role, content: finalContent };
            if (tableData) {
                msgObj.table_data = tableData;
            }
            list.push(msgObj);
        }
        return list;
    }

    /** Load history entry and fill chat (continue conversation). */
    function loadHistoryEntryAndContinue(entryId) {
        if (!chatMessages || !entryId) return;
        fetch('/api/ai/history/' + entryId + '/')
            .then(function (r) { return r.json(); })
            .then(function (data) {
                if (!data.success) {
                    console.warn('Failed to load history entry:', data.error);
                    return;
                }
                clearChat(); // reset chat before loading history

                if (data.conversation_history && Array.isArray(data.conversation_history) && data.conversation_history.length > 0) {
                    data.conversation_history.forEach((msg, index) => {
                        if (msg.role === 'user') {
                            addUserMessage(msg.content);
                        } else {
                            var assistantMsg = addAssistantMessage(false);
                            var contentDiv = assistantMsg.querySelector('.ai-chat-message-content');

                            // Extract text without code for display
                            const textWithoutCode = extractTextWithoutCode(msg.content);
                            if (textWithoutCode && textWithoutCode.length > 0) {
                                contentDiv.innerHTML = formatAiAssistantProse(textWithoutCode);
                            } else {
                                // leave empty if no text; table may follow
                                contentDiv.innerHTML = '';
                            }

                            // Render table for this message (or last message + data.table_data fallback)
                            let tbl = msg.table_data;
                            if (!tbl && index === data.conversation_history.length - 1) {
                                tbl = data.table_data;
                            }
                            if (tbl && tbl.headers && tbl.rows) {
                                displayTableDataInMessage(tbl, contentDiv);
                                assistantMsg.dataset.tableData = JSON.stringify(tbl);
                            }

                            // Keep raw text for getConversationHistory
                            assistantMsg.dataset.rawContent = msg.content;
                        }
                    });
                } else {
                    addUserMessage(data.question || '');
                    var assistantMsg = addAssistantMessage(false);
                    var contentDiv = assistantMsg ? assistantMsg.querySelector('.ai-chat-message-content') : null;
                    if (contentDiv) {
                        const answerText = data.answer || '';
                        const textWithoutCode = extractTextWithoutCode(answerText);

                        if (data.table_data && data.table_data.headers && data.table_data.rows) {
                            contentDiv.textContent = '';
                            displayTableDataInMessage(data.table_data, contentDiv);
                            assistantMsg.dataset.tableData = JSON.stringify(data.table_data);
                            if (textWithoutCode && textWithoutCode.length > 0) {
                                const textDiv = document.createElement('div');
                                textDiv.style.marginTop = '1rem';
                                textDiv.style.whiteSpace = 'pre-wrap';
                                textDiv.innerHTML = formatAiAssistantProse(textWithoutCode);
                                contentDiv.appendChild(textDiv);
                            }
                        } else {
                            if (textWithoutCode && textWithoutCode.length > 0) {
                                contentDiv.innerHTML = formatAiAssistantProse(textWithoutCode);
                            } else {
                                contentDiv.textContent = aiT('analysisComplete', 'Analysis complete.');
                            }
                        }
                        assistantMsg.dataset.rawContent = answerText;
                    }
                }

                currentAssistantMessage = null; // reset so a new question starts a new reply
                currentHistoryId = entryId; // current thread id
                if (clearBtn) clearBtn.classList.remove('d-none');
                scrollToBottom();
                if (typeof history !== 'undefined' && history.replaceState) {
                    var url = new URL(window.location);
                    url.searchParams.set('continue', currentHistoryId);
                    history.replaceState({}, '', url);
                }
            })
            .catch(function (err) {
                console.error('Error loading history entry:', err);
            });
    }

    function getCSRFToken() {
        const input = document.querySelector('input[name="csrfmiddlewaretoken"]');
        if (input && input.value) return input.value;
        const meta = document.querySelector('meta[name="csrf-token"]');
        if (meta && meta.getAttribute('content')) return meta.getAttribute('content');
        return '';
    }



    function extractTextWithoutCode(text) {
        // Text without code blocks (insights)
        if (!text) return '';

        let textWithoutCode = text;

        // Strip fenced code blocks
        textWithoutCode = textWithoutCode.replace(/```python\s*\n[\s\S]*?\n```/g, '');
        textWithoutCode = textWithoutCode.replace(/```\s*\n[\s\S]*?\n```/g, '');

        // Strip unclosed fences (streaming)
        textWithoutCode = textWithoutCode.replace(/```python\s*\n?[\s\S]*$/g, '');
        textWithoutCode = textWithoutCode.replace(/```\s*\n?[\s\S]*$/g, '');

        // Strip inline code
        textWithoutCode = textWithoutCode.replace(/`[^`]+`/g, '');

        // Trim whitespace
        textWithoutCode = textWithoutCode.trim();

        // Collapse 3+ newlines
        textWithoutCode = textWithoutCode.replace(/\n{3,}/g, '\n\n');

        return textWithoutCode;
    }

    /** Remove GFM-style pipe tables so we do not duplicate the server-rendered table. */
    function stripPipeMarkdownTables(text) {
        if (!text) return '';
        var lines = text.split('\n');
        var out = [];
        var inTable = false;
        for (var i = 0; i < lines.length; i++) {
            var line = lines[i];
            var looksRow = /^\s*\|.+\|\s*$/.test(line);
            var looksSep = /^\s*\|[\s\-:|\u2500\u253c]+\|\s*$/.test(line);
            if (looksRow || looksSep) {
                inTable = true;
                continue;
            }
            if (inTable && line.trim() === '') {
                inTable = false;
                continue;
            }
            if (!inTable) {
                out.push(line);
            }
        }
        return out.join('\n').replace(/\n{3,}/g, '\n\n').trim();
    }

    function getAiPageFiltersFromUrl() {
        var params = new URLSearchParams(window.location.search || '');
        var keys = ['month', 'year', 'filter_type', 'date_from', 'date_to', 'manager'];
        var out = {};
        keys.forEach(function (k) {
            var v = params.get(k);
            if (v !== null && String(v).trim() !== '') {
                out[k] = String(v).trim();
            }
        });
        return Object.keys(out).length ? out : null;
    }

    function sendAnalysisRequest(question, useStreaming = true) {
        console.log('Sending analysis request:', question);

        // Conversation history before loading indicator and new question
        var conversationHistory = getConversationHistory(false);

        // Reset assistant bubble so a new question does not reuse the old node
        currentAssistantMessage = null;

        // User message
        addUserMessage(question);

        // Clear input
        if (analysisQuestion) {
            analysisQuestion.value = '';
            analysisQuestion.style.height = 'auto';
        }

        // Loading indicator after user message
        addLoadingMessage(false);

        // Disable send
        if (analyzeBtn) {
            analyzeBtn.disabled = true;
        }

        // Show clear button
        if (clearBtn) {
            clearBtn.classList.remove('d-none');
        }

        var analyzePayload = {
            question: question,
            streaming: useStreaming,
            history_id: currentHistoryId
        };
        var pageFilters = getAiPageFiltersFromUrl();
        if (pageFilters) {
            analyzePayload.filters = pageFilters;
        }
        if (conversationHistory.length) {
            analyzePayload.conversation_history = conversationHistory;
        }

        // POST analyze (filters = same query string as dashboard / sales / expenses)
        fetch('/api/ai/analyze/', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCSRFToken(),
            },
            body: JSON.stringify(analyzePayload)
        })
            .then(response => {
                if (!response.ok) {
                    return response.json().then(data => {
                        throw new Error(data.error || aiT('requestFailed', 'Error while executing request'));
                    });
                }

                // Streaming (text/event-stream)?
                const contentType = response.headers.get('content-type') || '';
                if (contentType.includes('text/event-stream')) {
                    // Handle SSE stream
                    return handleStreamingResponse(response);
                } else {
                    // Handle JSON
                    return response.json().then(handleNonStreamingResponse);
                }
            })
            .catch(error => {
                console.error('Error sending request:', error);
                showError(error.message || aiT('analysisFailed', 'An error occurred while running the analysis'));
            })
            .finally(() => {
                // Remove loading indicator
                removeLoadingMessage();

                // Re-enable send
                if (analyzeBtn) {
                    analyzeBtn.disabled = false;
                }

                // Focus input after request completes
                if (analysisQuestion) {
                    setTimeout(() => {
                        analysisQuestion.focus();
                    }, 100);
                }
            });
    }

    function handleStreamingResponse(response) {
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        let accumulatedText = '';

        function readChunk() {
            return reader.read().then(({ done, value }) => {
                if (done) {
                    return;
                }

                buffer += decoder.decode(value, { stream: true });
                const lines = buffer.split('\n');
                buffer = lines.pop() || '';

                lines.forEach(line => {
                    if (line.startsWith('data: ')) {
                        const data = line.slice(6);
                        if (data === '[DONE]') {
                            return;
                        }

                        try {
                            const json = JSON.parse(data);

                            if (json.error) {
                                showError(json.error);
                                return;
                            }

                            if (json.chunk) {
                                accumulatedText += json.chunk;
                            }

                            // Apply full_text when provided
                            if (json.full_text) {
                                accumulatedText = json.full_text;
                            }

                            if (json.usage) {
                                updateTokenUsage(json.usage);
                            }

                            if (json.history_id && !currentHistoryId) {
                                currentHistoryId = json.history_id;
                                if (typeof history !== 'undefined' && history.replaceState) {
                                    var url = new URL(window.location);
                                    url.searchParams.set('continue', currentHistoryId);
                                    history.replaceState({}, '', url);
                                }
                            }

                            if (json.done) {
                                // Remove loading indicator
                                removeLoadingMessage();

                                const fullText = json.full_text || accumulatedText;

                                // Reuse single assistant bubble (avoid duplicate)
                                if (!currentAssistantMessage) {
                                    currentAssistantMessage = addAssistantMessage(false);
                                }
                                const contentDiv = currentAssistantMessage.querySelector('.ai-chat-message-content');
                                if (!contentDiv) return;
                                contentDiv.innerHTML = '';

                                if (json.table_data && json.table_data.headers && json.table_data.rows) {
                                    displayTableDataInMessage(json.table_data, contentDiv);
                                    currentAssistantMessage.dataset.tableData = JSON.stringify(json.table_data);
                                    const textWithoutCode = stripPipeMarkdownTables(extractTextWithoutCode(fullText));
                                    if (textWithoutCode && textWithoutCode.length > 0) {
                                        const textDiv = document.createElement('div');
                                        textDiv.style.marginTop = '1rem';
                                        textDiv.style.whiteSpace = 'pre-wrap';
                                        textDiv.innerHTML = formatAiAssistantProse(textWithoutCode);
                                        contentDiv.appendChild(textDiv);
                                    }
                                } else {
                                    const textWithoutCode = extractTextWithoutCode(fullText);
                                    if (textWithoutCode && textWithoutCode.length > 0) {
                                        contentDiv.innerHTML = formatAiAssistantProse(textWithoutCode);
                                    } else {
                                        contentDiv.textContent = aiT('analysisCompleteNoData', 'Analysis complete. No data.');
                                    }
                                }

                                // Store full text for getConversationHistory
                                currentAssistantMessage.dataset.rawContent = fullText;

                                scrollToBottom();
                            } else {
                                // Single streaming bubble, update as chunks arrive
                                if (!currentAssistantMessage) {
                                    removeLoadingMessage();
                                    currentAssistantMessage = addAssistantMessage(false);
                                }

                                const textWithoutCode = extractTextWithoutCode(accumulatedText);
                                const contentDiv = currentAssistantMessage.querySelector('.ai-chat-message-content');
                                if (textWithoutCode && textWithoutCode.length > 0) {
                                    contentDiv.innerHTML = formatAiAssistantProse(textWithoutCode);
                                } else {
                                    contentDiv.innerHTML = '<span class="ai-chat-gathering-info"><i class="bi bi-gear-wide-connected spin ms-1 me-2"></i>' + escapeHtml(aiT('gatheringInfo', 'Gathering information...')) + '</span>';
                                }
                                scrollToBottom();
                            }
                        } catch (e) {
                            console.error('JSON parsing error:', e);
                        }
                    }
                });

                return readChunk();
            });
        }

        return readChunk();
    }

    function handleNonStreamingResponse(data) {
        console.log('Handling non-streaming response:', data);

        if (data.error) {
            showError(data.error);
            return;
        }

        // Remove loading
        removeLoadingMessage();

        const fullText = data.analysis || data.full_text || '';

        // Assistant message after user (order)
        currentAssistantMessage = addAssistantMessage(false);
        const contentDiv = currentAssistantMessage.querySelector('.ai-chat-message-content');

        if (data.history_id && !currentHistoryId) {
            currentHistoryId = data.history_id;
            if (typeof history !== 'undefined' && history.replaceState) {
                var url = new URL(window.location);
                url.searchParams.set('continue', currentHistoryId);
                history.replaceState({}, '', url);
            }
        }

        if (data.table_data && data.table_data.headers && data.table_data.rows) {
            // Has table: show table + ChatGPT prose
            contentDiv.textContent = ''; // clear before append
            displayTableDataInMessage(data.table_data, contentDiv);
            currentAssistantMessage.dataset.tableData = JSON.stringify(data.table_data);

            // Show ChatGPT text without code
            if (fullText) {
                const textWithoutCode = stripPipeMarkdownTables(extractTextWithoutCode(fullText));
                if (textWithoutCode && textWithoutCode.length > 0) {
                    const textDiv = document.createElement('div');
                    textDiv.style.marginTop = '1rem';
                    textDiv.style.whiteSpace = 'pre-wrap';
                    textDiv.innerHTML = formatAiAssistantProse(textWithoutCode);
                    contentDiv.appendChild(textDiv);
                }
            }
        } else if (fullText) {
            // No table: free-form text
            const textWithoutCode = extractTextWithoutCode(fullText);
            if (textWithoutCode && textWithoutCode.length > 0) {
                contentDiv.innerHTML = formatAiAssistantProse(textWithoutCode);
            } else {
                // No useful text and no table
                contentDiv.textContent = aiT('analysisCompleteNoData', 'Analysis complete. No data.');
            }
        } else {
            console.warn('No analysis data in response');
            contentDiv.textContent = aiT('noData', 'No data.');
        }

        currentAssistantMessage.dataset.rawContent = fullText;

        scrollToBottom();

        if (data.usage) {
            updateTokenUsage(data.usage);
        }
    }

    function showError(message) {
        removeLoadingMessage();
        currentAssistantMessage = addAssistantMessage(true);
        const contentDiv = currentAssistantMessage.querySelector('.ai-chat-message-content');
        contentDiv.textContent = aiT('errorPrefix', 'Error:') + ' ' + message;
        contentDiv.style.color = '#ff4d4d';
        scrollToBottom();
    }

    function updateTokenUsage(usage) {
        if (tokenUsage && tokenInfoText) {
            const total = usage.total_tokens || (usage.prompt_tokens || 0) + (usage.completion_tokens || 0);
            const tokLine = aiT('tokenUsageLine', 'Tokens: {total} (prompt: {prompt}, completion: {completion})');
            tokenInfoText.textContent = tokLine
                .replace('{total}', String(total))
                .replace('{prompt}', String(usage.prompt_tokens || 0))
                .replace('{completion}', String(usage.completion_tokens || 0));
            tokenUsage.classList.remove('d-none');
        }
    }

    /**
     * Bar / mixed chart for AI tables: 2+ months in rows, or 2+ managers (pivot or single metric).
     */
    function appendAiTableChartIfEligible(tableData, container, translateHeaderFn) {
        if (typeof Chart === 'undefined' || !tableData || !tableData.headers || !tableData.rows || !container) {
            return;
        }
        var translateAiHeader = typeof translateHeaderFn === 'function' ? translateHeaderFn : function (h) {
            return String(h || '');
        };
        var headersRaw = Array.isArray(tableData.headers) ? tableData.headers : [];
        var rows = Array.isArray(tableData.rows) ? tableData.rows : [];
        var translatedHeaders = headersRaw.map(translateAiHeader);
        if (!Array.isArray(rows) || rows.length < 1 || !Array.isArray(headersRaw) || headersRaw.length < 2) {
            return;
        }

        function parseNumericCell(v) {
            if (v === null || v === undefined) return NaN;
            if (typeof v === 'number' && !isNaN(v)) return v;
            var s = String(v).trim().replace(/\u00A0/g, ' ').replace(/₴/g, '');
            s = s.replace(/\s/g, '').replace(/,/g, '.');
            var n = parseFloat(s);
            return isNaN(n) ? NaN : n;
        }

        var headersLower = headersRaw.map(function (h) { return String(h || '').trim().toLowerCase(); });

        /** Metric name from a period column header (drops trailing month name / date tail). */
        function stripTrailingMonthFromMetricHeader(rawHeader) {
            var s = String(translateAiHeader(rawHeader) || '').replace(/\s+/g, ' ').trim();
            if (!s) return s;
            var monthTail = /\s+(?:январ(?:я)?|феврал(?:я)?|марта?|апрел(?:я)?|ма[йя]|июн(?:я)?|июл(?:я)?|августа?|сентябр(?:я)?|октябр(?:я)?|ноябр(?:я)?|декабр(?:я)?|january|february|march|april|may|june|july|august|september|october|november|december|jan\.?|feb\.?|mar\.?|apr\.?|jun\.?|jul\.?|aug\.?|sep\.?|oct\.?|nov\.?|dec\.?|січ(?:ень)?|лют(?:ий)?|берез(?:ень)?|квіт(?:ень)?|трав(?:ень)?|черв(?:ень)?|лип(?:ень)?|серп(?:ень)?|верес(?:ень)?|жовт(?:ень)?|листоп(?:ад)?|груд(?:ень)?)(?:\s+\d{2,4})?\s*$/i;
            var prev;
            do {
                prev = s;
                s = s.replace(monthTail, '').trim();
                s = s.replace(/\s*[—–\-]\s*\d{1,2}[./]\d{1,2}[./]\d{2,4}\s*$/i, '').trim();
            } while (s !== prev);
            return s || String(translateAiHeader(rawHeader) || '').trim();
        }

        function idxAny(partsList) {
            for (var i = 0; i < headersLower.length; i++) {
                var h = headersLower[i];
                for (var p = 0; p < partsList.length; p++) {
                    var parts = partsList[p];
                    var ok = true;
                    for (var j = 0; j < parts.length; j++) {
                        if (!h.includes(parts[j])) {
                            ok = false;
                            break;
                        }
                    }
                    if (ok) return i;
                }
            }
            return -1;
        }

        function isDealsHeader(h) {
            return h.includes('deal') || h.includes('сдел') || h.includes('угод') || h.includes('кільк') || h.includes('record count');
        }

        function findManagerCol() {
            for (var i = 0; i < headersLower.length; i++) {
                var h = headersLower[i];
                if (h.includes('менедж') || h.includes('manager') || h.includes('керів')) return i;
            }
            return -1;
        }

        function findCompanyCol() {
            for (var i = 0; i < headersLower.length; i++) {
                var h = headersLower[i];
                if (h.includes('компан') || h.includes('company')) return i;
            }
            return -1;
        }

        /** CRM aggregate by expense_type (UK/RU/EN / tool keys). */
        function findExpenseTypeCol() {
            for (var i = 0; i < headersLower.length; i++) {
                var h = headersLower[i];
                if (h.includes('expense_type')) return i;
                if (h.includes('expense') && h.includes('type')) return i;
                if (h.includes('вид') && (h.includes('расход') || h.includes('витрат'))) return i;
                if (h.includes('тип') && (h.includes('расход') || h.includes('витрат'))) return i;
                if ((h.includes('категор') || h.includes('category')) && (h.includes('витрат') || h.includes('расход') || h.includes('expense'))) return i;
            }
            return -1;
        }

        var monthIdx = idxAny([['меся'], ['month'], ['міся']]);
        var salesIdx = idxAny([['общ', 'продаж'], ['total', 'sale'], ['всього', 'продаж']]);
        var dealsIdx = idxAny([
            ['колич', 'сдел'],
            ['deals'],
            ['кільк', 'угод'],
            ['колич', 'запис'],
            ['кільк', 'запис'],
            ['кількість', 'запис'],
            ['record', 'count'],
            ['operations', 'count'],
        ]);
        var amountTotalIdx = idxAny([
            ['общ', 'сумм'],
            ['total', 'amount'],
            ['всього', 'сума'],
            ['сума', 'продаж'],
        ]);

        var chartPayload = null;
        var chartsFromPivot = null;

        /** Company, expense type, etc.: one category column + total amount (+ optional record-count line). */
        function buildCategoryBarLinePayload(categoryCol, amountIdx) {
            if (categoryCol < 0 || amountIdx < 0 || categoryCol === amountIdx || rows.length < 1) {
                return null;
            }
            var lbl = [];
            var amt = [];
            var cnt = [];
            for (var rxi = 0; rxi < rows.length; rxi++) {
                var rowX = rows[rxi];
                if (!rowX || rowX.length <= Math.max(categoryCol, amountIdx)) continue;
                lbl.push(String(rowX[categoryCol] || '').trim() || ('#' + (rxi + 1)));
                amt.push(parseNumericCell(rowX[amountIdx]));
                if (dealsIdx >= 0 && rowX.length > dealsIdx) {
                    var cvx = parseNumericCell(rowX[dealsIdx]);
                    cnt.push(isNaN(cvx) ? 0 : cvx);
                }
            }
            if (lbl.length < 1 || amt.length !== lbl.length) {
                return null;
            }
            var ds = [{
                type: 'bar',
                label: translatedHeaders[amountIdx],
                data: amt,
                backgroundColor: 'rgba(108, 99, 255, 0.85)',
                borderColor: 'rgba(108, 99, 255, 1)',
                borderWidth: 1.5,
                borderRadius: 6,
                yAxisID: 'y'
            }];
            var useCnt = dealsIdx >= 0 && cnt.length === amt.length && cnt.some(function (x) { return x > 0; });
            if (useCnt) {
                ds.push({
                    type: 'line',
                    label: translatedHeaders[dealsIdx],
                    data: cnt,
                    borderColor: 'rgba(255, 106, 51, 0.95)',
                    backgroundColor: 'rgba(255, 106, 51, 0.1)',
                    borderWidth: 2,
                    fill: false,
                    yAxisID: 'y1',
                    tension: 0.25,
                    pointRadius: 4
                });
            }
            var ctitle = translatedHeaders[categoryCol] + ' — ' + translatedHeaders[amountIdx];
            if (useCnt) {
                ctitle += ' / ' + translatedHeaders[dealsIdx];
            }
            return {
                labels: lbl,
                datasets: ds,
                dualAxis: useCnt,
                chartTitle: ctitle,
                chartHeight: Math.min(360, 220 + lbl.length * 28),
            };
        }

        if (monthIdx >= 0 && salesIdx >= 0 && monthIdx !== salesIdx && rows.length >= 2) {
            var mgrCk = findManagerCol();
            if (mgrCk < 0 || mgrCk === monthIdx) {
                var labelsM = [];
                var salesDataM = [];
                var dealsDataM = [];
                for (var ri = 0; ri < rows.length; ri++) {
                    var row = rows[ri];
                    if (!row || row.length <= Math.max(monthIdx, salesIdx)) continue;
                    labelsM.push(String(row[monthIdx] || ''));
                    salesDataM.push(parseNumericCell(row[salesIdx]));
                    if (dealsIdx >= 0 && row.length > dealsIdx) {
                        var dv = parseNumericCell(row[dealsIdx]);
                        dealsDataM.push(isNaN(dv) ? 0 : dv);
                    }
                }
                if (labelsM.length >= 2) {
                    var dsM = [{
                        type: 'bar',
                        label: translatedHeaders[salesIdx],
                        data: salesDataM,
                        backgroundColor: 'rgba(108, 99, 255, 0.85)',
                        borderColor: 'rgba(108, 99, 255, 1)',
                        borderWidth: 1.5,
                        borderRadius: 6,
                        yAxisID: 'y'
                    }];
                    var useDeals = dealsIdx >= 0 && dealsDataM.length === salesDataM.length && dealsDataM.some(function (x) { return x > 0; });
                    if (useDeals) {
                        dsM.push({
                            type: 'line',
                            label: translatedHeaders[dealsIdx],
                            data: dealsDataM,
                            borderColor: 'rgba(255, 106, 51, 0.95)',
                            backgroundColor: 'rgba(255, 106, 51, 0.1)',
                            borderWidth: 2,
                            fill: false,
                            yAxisID: 'y1',
                            tension: 0.25,
                            pointRadius: 4
                        });
                    }
                    var chartTitleM = translatedHeaders[monthIdx] + ' — ' + translatedHeaders[salesIdx];
                    if (useDeals) {
                        chartTitleM += ' / ' + translatedHeaders[dealsIdx];
                    }
                    chartPayload = { labels: labelsM, datasets: dsM, dualAxis: useDeals, chartTitle: chartTitleM };
                }
            }
        }

        if (!chartPayload) {
            var compCol = findCompanyCol();
            var amtIdxCat = amountTotalIdx >= 0 ? amountTotalIdx : salesIdx;
            chartPayload = buildCategoryBarLinePayload(compCol, amtIdxCat);
        }

        if (!chartPayload) {
            var expCol = findExpenseTypeCol();
            var amtIdxExp = amountTotalIdx >= 0 ? amountTotalIdx : salesIdx;
            chartPayload = buildCategoryBarLinePayload(expCol, amtIdxExp);
        }

        if (!chartPayload) {
            var mgrCol = findManagerCol();
            if (mgrCol >= 0 && headersLower.length >= 3) {
                var periodCols = [];
                for (var cj = 0; cj < headersLower.length; cj++) {
                    if (cj === mgrCol) continue;
                    var hh = headersLower[cj];
                    if (isDealsHeader(hh)) continue;
                    var allNum = true;
                    for (var rk = 0; rk < rows.length; rk++) {
                        var rw = rows[rk];
                        if (!rw || rw.length <= cj) {
                            allNum = false;
                            break;
                        }
                        if (isNaN(parseNumericCell(rw[cj]))) {
                            allNum = false;
                            break;
                        }
                    }
                    if (allNum && rows.length > 0) periodCols.push(cj);
                }
                if (periodCols.length >= 2 && rows.length >= 1) {
                    var xLabels = periodCols.map(function (ci) { return translatedHeaders[ci]; });
                    var pal = ['rgba(108, 99, 255, 0.85)', 'rgba(255, 212, 59, 0.9)', 'rgba(255, 106, 51, 0.9)', 'rgba(76, 217, 100, 0.9)', 'rgba(156, 39, 176, 0.85)', 'rgba(129, 199, 132, 0.9)', 'rgba(255, 152, 0, 0.9)', 'rgba(100, 181, 246, 0.9)'];
                    var borders = ['rgba(108, 99, 255, 1)', 'rgba(255, 212, 59, 1)', 'rgba(255, 106, 51, 1)', 'rgba(76, 217, 100, 1)', 'rgba(156, 39, 176, 1)', 'rgba(129, 199, 132, 1)', 'rgba(255, 152, 0, 1)', 'rgba(100, 181, 246, 1)'];

                    var monthSalesTotals = periodCols.map(function (ci) {
                        var s = 0;
                        for (var ri = 0; ri < rows.length; ri++) {
                            s += parseNumericCell(rows[ri][ci]);
                        }
                        return s;
                    });
                    var monthDealsTotals = periodCols.map(function (ci) {
                        var di = ci + 1;
                        var t = 0;
                        if (di < headersLower.length && isDealsHeader(headersLower[di])) {
                            for (var ri = 0; ri < rows.length; ri++) {
                                t += parseNumericCell(rows[ri][di]);
                            }
                        }
                        return t;
                    });
                    var useDealsTeam = monthDealsTotals.some(function (x) { return x > 0; });

                    var metricBarLabel = stripTrailingMonthFromMetricHeader(headersRaw[periodCols[0]]);
                    var mgrDimLabel = translatedHeaders[mgrCol];
                    var dealsColForTeam = -1;
                    if (useDealsTeam) {
                        var dTry = periodCols[0] + 1;
                        if (dTry < headersLower.length && isDealsHeader(headersLower[dTry])) {
                            dealsColForTeam = dTry;
                        }
                    }
                    var dealsLineLabel = dealsColForTeam >= 0
                        ? translatedHeaders[dealsColForTeam]
                        : aiT('chartDeals', 'Deals');

                    var teamDs = [{
                        type: 'bar',
                        label: metricBarLabel || translatedHeaders[periodCols[0]],
                        data: monthSalesTotals,
                        backgroundColor: 'rgba(108, 99, 255, 0.85)',
                        borderColor: 'rgba(108, 99, 255, 1)',
                        borderWidth: 1.5,
                        borderRadius: 6,
                        yAxisID: 'y'
                    }];
                    if (useDealsTeam) {
                        teamDs.push({
                            type: 'line',
                            label: dealsLineLabel,
                            data: monthDealsTotals,
                            borderColor: 'rgba(255, 106, 51, 0.95)',
                            backgroundColor: 'rgba(255, 106, 51, 0.08)',
                            borderWidth: 2,
                            fill: false,
                            yAxisID: 'y1',
                            tension: 0.25,
                            pointRadius: 4
                        });
                    }

                    var mgrTotals = [];
                    for (var mri = 0; mri < rows.length; mri++) {
                        var rrowT = rows[mri];
                        var totS = 0;
                        for (var pc = 0; pc < periodCols.length; pc++) {
                            totS += parseNumericCell(rrowT[periodCols[pc]]);
                        }
                        mgrTotals.push({ name: String(rrowT[mgrCol] || ('#' + (mri + 1))), total: totS, idx: mri });
                    }
                    mgrTotals.sort(function (a, b) { return b.total - a.total; });
                    var topN = Math.min(8, Math.max(3, rows.length));
                    var topSlice = mgrTotals.filter(function (x) { return x.total > 0; }).slice(0, topN);
                    if (!topSlice.length) {
                        topSlice = mgrTotals.slice(0, topN);
                    }

                    var periodHint = xLabels.length <= 5
                        ? xLabels.join(', ')
                        : (xLabels[0] + ' … ' + xLabels[xLabels.length - 1]);
                    var titleTeam = (metricBarLabel + ' — ' + mgrDimLabel + (periodHint ? ' · ' + periodHint : '')).trim();
                    var titleTop = (mgrDimLabel + ' — ' + metricBarLabel).trim();
                    var titleDetail = (metricBarLabel + ' · ' + mgrDimLabel).trim();

                    chartsFromPivot = [];
                    chartsFromPivot.push({
                        title: titleTeam,
                        height: 268,
                        labels: xLabels,
                        datasets: teamDs,
                        dualAxis: useDealsTeam
                    });

                    if (topSlice.length >= 1) {
                        chartsFromPivot.push({
                            title: titleTop,
                            height: Math.min(420, 56 + topSlice.length * 36),
                            labels: topSlice.map(function (x) { return x.name; }),
                            datasets: [{
                                label: metricBarLabel || translatedHeaders[periodCols[0]],
                                data: topSlice.map(function (x) { return x.total; }),
                                backgroundColor: 'rgba(76, 217, 100, 0.82)',
                                borderColor: 'rgba(76, 217, 100, 1)',
                                borderWidth: 1.5,
                                borderRadius: 4
                            }],
                            dualAxis: false,
                            indexAxis: 'y'
                        });
                    }

                    var mgrDatasetsDetail = [];
                    for (var ts = 0; ts < topSlice.length; ts++) {
                        var mr = topSlice[ts].idx;
                        var rrow = rows[mr];
                        var mgrName = String(rrow[mgrCol] || ('#' + (mr + 1)));
                        var series = periodCols.map(function (ci) { return parseNumericCell(rrow[ci]); });
                        mgrDatasetsDetail.push({
                            label: mgrName,
                            data: series,
                            backgroundColor: pal[ts % pal.length],
                            borderColor: borders[ts % borders.length],
                            borderWidth: 1.5,
                            borderRadius: 4
                        });
                    }
                    if (mgrDatasetsDetail.length > 0) {
                        chartsFromPivot.push({
                            title: titleDetail,
                            height: 300,
                            labels: xLabels,
                            datasets: mgrDatasetsDetail,
                            dualAxis: false
                        });
                    }

                    chartPayload = null;
                }
            }
        }

        if (!chartPayload && !(chartsFromPivot && chartsFromPivot.length)) {
            var mgrCol2 = findManagerCol();
            if (mgrCol2 >= 0) {
                var salesColCandidates = [];
                for (var sc = 0; sc < headersLower.length; sc++) {
                    if (sc === mgrCol2) continue;
                    if (monthIdx >= 0 && sc === monthIdx) continue;
                    var hhh = headersLower[sc];
                    if (isDealsHeader(hhh)) continue;
                    if (!(hhh.includes('sale') || hhh.includes('продаж') || hhh.includes('выр') || hhh.includes('revenue') || hhh.includes('сума') || hhh.includes('total'))) continue;
                    var ok2 = true;
                    for (var r2 = 0; r2 < rows.length; r2++) {
                        var rw2 = rows[r2];
                        if (!rw2 || rw2.length <= sc) {
                            ok2 = false;
                            break;
                        }
                        if (isNaN(parseNumericCell(rw2[sc]))) {
                            ok2 = false;
                            break;
                        }
                    }
                    if (ok2) salesColCandidates.push(sc);
                }
                if (salesColCandidates.length === 1 && rows.length >= 2) {
                    var scIdx = salesColCandidates[0];
                    var barLabels = rows.map(function (rw) { return String(rw[mgrCol2] || ''); });
                    var barData = rows.map(function (rw) { return parseNumericCell(rw[scIdx]); });
                    chartPayload = {
                        labels: barLabels,
                        datasets: [{
                            label: translatedHeaders[scIdx],
                            data: barData,
                            backgroundColor: 'rgba(108, 99, 255, 0.85)',
                            borderColor: 'rgba(108, 99, 255, 1)',
                            borderWidth: 1.5,
                            borderRadius: 6
                        }],
                        dualAxis: false,
                        chartTitle: translatedHeaders[mgrCol2] + ' — ' + translatedHeaders[scIdx]
                    };
                }
            }
        }

        if (!chartPayload && !(chartsFromPivot && chartsFromPivot.length) && tableData._combo_salary_expenses && rows.length >= 1) {
            var palCombo = ['rgba(108, 99, 255, 0.85)', 'rgba(255, 212, 59, 0.9)', 'rgba(255, 106, 51, 0.9)', 'rgba(76, 217, 100, 0.82)'];
            var bordCombo = ['rgba(108, 99, 255, 1)', 'rgba(255, 212, 59, 1)', 'rgba(255, 106, 51, 1)', 'rgba(76, 217, 100, 1)'];
            var dsCombo = [];
            for (var hci = 1; hci < headersRaw.length; hci++) {
                var allNumC = true;
                var colValsC = [];
                for (var rci = 0; rci < rows.length; rci++) {
                    var vv = parseNumericCell(rows[rci][hci]);
                    if (isNaN(vv)) {
                        allNumC = false;
                        break;
                    }
                    colValsC.push(vv);
                }
                if (allNumC && colValsC.length === rows.length) {
                    var pi = dsCombo.length;
                    dsCombo.push({
                        type: 'bar',
                        label: translatedHeaders[hci],
                        data: colValsC,
                        backgroundColor: palCombo[pi % palCombo.length],
                        borderColor: bordCombo[pi % bordCombo.length],
                        borderWidth: 1.5,
                        borderRadius: 6,
                        yAxisID: 'y'
                    });
                }
            }
            if (dsCombo.length >= 1) {
                var catLabsCombo = rows.map(function (r) { return String(r[0] || '').trim() || '—'; });
                var comboTitle = catLabsCombo.filter(function (x) { return x && x !== '—'; }).join(' · ');
                if (!comboTitle) {
                    comboTitle = translatedHeaders[0];
                }
                chartPayload = {
                    labels: catLabsCombo,
                    datasets: dsCombo,
                    dualAxis: false,
                    chartTitle: comboTitle,
                    chartHeight: Math.min(320, 180 + rows.length * 48)
                };
            }
        }

        var root = document.documentElement;
        var gridColor = getComputedStyle(root).getPropertyValue('--chart-grid-color').trim() || 'rgba(228, 231, 238, 0.5)';
        var chartTextColor = getComputedStyle(root).getPropertyValue('--chart-text-color').trim() || '#2E2E3A';
        var chartAxisColor = getComputedStyle(root).getPropertyValue('--chart-axis-color').trim() || '#6F7381';
        var isMobileChart = typeof window.matchMedia === 'function' && window.matchMedia('(max-width: 768px)').matches;

        /** Axis line along scale (Chart.js v3.7+ `border`; older builds may ignore). */
        function axisLineBorder() {
            return { display: true, color: chartAxisColor, width: 1 };
        }

        function makeScalesVerticalCategory(dualAxis) {
            var b = axisLineBorder();
            var sc = {
                x: {
                    grid: { display: false },
                    border: b,
                    ticks: {
                        color: chartAxisColor,
                        font: { size: isMobileChart ? 10 : 12 },
                        maxRotation: 65,
                        minRotation: 0,
                        autoSkip: false
                    }
                },
                y: {
                    beginAtZero: true,
                    position: 'left',
                    grid: { color: gridColor, lineWidth: 1 },
                    border: b,
                    ticks: { color: chartAxisColor, font: { size: 12 } }
                }
            };
            if (dualAxis) {
                sc.y1 = {
                    beginAtZero: true,
                    position: 'right',
                    grid: { drawOnChartArea: false },
                    border: b,
                    ticks: { color: chartAxisColor, font: { size: 11 } }
                };
            }
            return sc;
        }

        function makeScalesHorizontalBar() {
            var b = axisLineBorder();
            return {
                x: {
                    beginAtZero: true,
                    position: 'bottom',
                    grid: { color: gridColor, lineWidth: 1 },
                    border: b,
                    ticks: { color: chartAxisColor, font: { size: 11 } }
                },
                y: {
                    grid: { display: false },
                    border: b,
                    ticks: {
                        color: chartAxisColor,
                        font: { size: isMobileChart ? 10 : 11 },
                        maxRotation: 0,
                        autoSkip: false
                    }
                }
            };
        }

        function tooltipValue(context) {
            var horizontal =
                context.chart &&
                context.chart.options &&
                context.chart.options.indexAxis === 'y';
            var v = horizontal ? context.parsed.x : context.parsed.y;
            if (v === null || v === undefined) {
                v = horizontal ? context.parsed.y : context.parsed.x;
            }
            if (v === null || v === undefined) return '';
            return Number(v).toLocaleString(undefined, { maximumFractionDigits: 2 });
        }

        function mountOneAiChart(spec, showDataHint) {
            var wrap = document.createElement('div');
            wrap.className = 'ai-chat-chart-wrap';

            var titleEl = document.createElement('div');
            titleEl.className = 'small fw-semibold mb-1';
            titleEl.style.color = 'var(--text-primary, inherit)';
            var resolvedTitle = spec.title;
            if (!resolvedTitle && spec.datasets && spec.datasets[0] && spec.datasets[0].label) {
                resolvedTitle = String(spec.datasets[0].label);
            }
            if (!resolvedTitle) {
                resolvedTitle = aiT('comparisonChart', 'Comparison chart');
            }
            titleEl.textContent = resolvedTitle;
            wrap.appendChild(titleEl);

            if (showDataHint) {
                var hintEl = document.createElement('div');
                hintEl.className = 'ai-chat-chart-hint small';
                hintEl.textContent = aiT('chartDataHint', 'Built from the table above — same numbers.');
                wrap.appendChild(hintEl);
            }

            var canvasHost = document.createElement('div');
            canvasHost.className = 'ai-chat-chart-canvas-inner';
            canvasHost.style.height = (spec.height || 280) + 'px';
            canvasHost.style.position = 'relative';
            canvasHost.style.width = '100%';

            var canvas = document.createElement('canvas');
            canvas.setAttribute('role', 'img');
            canvas.setAttribute('aria-label', resolvedTitle);
            canvasHost.appendChild(canvas);
            wrap.appendChild(canvasHost);
            container.appendChild(wrap);

            var ctx = canvas.getContext('2d');
            if (canvas._aiChart) {
                canvas._aiChart.destroy();
            }
            var idxAxis = spec.indexAxis || '';
            var scales = idxAxis === 'y' ? makeScalesHorizontalBar() : makeScalesVerticalCategory(!!spec.dualAxis);
            var chartOptions = {
                responsive: true,
                maintainAspectRatio: false,
                interaction: { intersect: false, mode: 'index' },
                scales: scales,
                plugins: {
                    datalabels: { display: false },
                    legend: {
                        display: true,
                        position: 'bottom',
                        labels: { color: chartTextColor, font: { size: 11 }, usePointStyle: true, padding: 10 }
                    },
                    tooltip: {
                        backgroundColor: 'rgba(0,0,0,0.82)',
                        titleFont: { size: 13, weight: '600' },
                        bodyFont: { size: 12 },
                        callbacks: {
                            label: function (context) {
                                var lbl = context.dataset.label || '';
                                if (lbl) lbl += ': ';
                                lbl += tooltipValue(context);
                                return lbl;
                            }
                        }
                    }
                }
            };
            if (idxAxis === 'y') {
                chartOptions.indexAxis = 'y';
            }
            canvas._aiChart = new Chart(ctx, {
                type: 'bar',
                data: { labels: spec.labels, datasets: spec.datasets },
                options: chartOptions
            });
        }

        if (chartsFromPivot && chartsFromPivot.length) {
            for (var ci = 0; ci < chartsFromPivot.length; ci++) {
                var sp = chartsFromPivot[ci];
                if (sp && sp.labels && sp.datasets && sp.datasets.length) {
                    mountOneAiChart(sp, ci === 0);
                }
            }
            return;
        }

        if (!chartPayload || !chartPayload.datasets || !chartPayload.labels) {
            return;
        }

        var singleTitle = chartPayload.chartTitle;
        if (!singleTitle && chartPayload.datasets && chartPayload.datasets[0] && chartPayload.datasets[0].label) {
            singleTitle = String(chartPayload.datasets[0].label);
        }
        mountOneAiChart({
            title: singleTitle || '',
            height: chartPayload.chartHeight || 260,
            labels: chartPayload.labels,
            datasets: chartPayload.datasets,
            dualAxis: !!chartPayload.dualAxis
        }, true);
    }

    function displayTableDataInMessage(tableData, container) {
        if (!tableData || !tableData.headers || !tableData.rows || !container) {
            return;
        }

        function detectUiLang() {
            const htmlLang = (document.documentElement.getAttribute('lang') || '').toLowerCase();
            if (htmlLang.startsWith('uk')) return 'uk';
            if (htmlLang.startsWith('ru')) return 'ru';
            return 'en';
        }

        function translateAiHeader(header) {
            const lang = detectUiLang();
            if (lang === 'en') return String(header || '');
            const raw = String(header || '');
            const key = raw.trim().toLowerCase();
            const dictUk = {
                'manager': 'Менеджер',
                'month': 'Місяць',
                'period': 'Період',
                'total sales': 'Загальні продажі',
                'total amount': 'Загальна сума',
                'deals count': 'Кількість угод',
                'record count': 'Кількість записів',
                'average deal': 'Середній чек',
                'avg amount': 'Середня сума',
                'max deal': 'Макс. угода',
                'max amount': 'Макс. сума',
                'total expenses': 'Загальні витрати',
                'operations count': 'Кількість операцій',
                'payout amount': 'Сума виплат',
                'total salary': 'Загальна зарплата',
                'company': 'Компанія',
                'employee': 'Співробітник',
                'expense type': 'Вид витрат',
                'average amount': 'Середня сума',
            };
            const dictRu = {
                'manager': 'Менеджер',
                'month': 'Месяц',
                'period': 'Период',
                'total sales': 'Общие продажи',
                'total amount': 'Общая сумма',
                'deals count': 'Количество сделок',
                'record count': 'Количество записей',
                'average deal': 'Средний чек',
                'avg amount': 'Средняя сумма',
                'max deal': 'Макс. сделка',
                'max amount': 'Макс. сумма',
                'total expenses': 'Общие расходы',
                'operations count': 'Количество операций',
                'payout amount': 'Сумма выплат',
                'total salary': 'Сумма зарплаты',
                'company': 'Компания',
                'employee': 'Сотрудник',
                'expense type': 'Вид расходов',
                'average amount': 'Средняя сумма',
            };
            const dict = lang === 'uk' ? dictUk : dictRu;
            return dict[key] || raw;
        }

        appendAiTableChartIfEligible(tableData, container, translateAiHeader);

        function tryParseJsonCell(value) {
            if (typeof value !== 'string') return value;
            const trimmed = value.trim();
            if (!trimmed) return value;
            if ((trimmed.startsWith('{') && trimmed.endsWith('}')) || (trimmed.startsWith('[') && trimmed.endsWith(']'))) {
                try {
                    return JSON.parse(trimmed);
                } catch (e) {
                    return value;
                }
            }
            return value;
        }

        function appendStructuredValue(target, value, depth) {
            const level = depth || 0;
            if (level > 2) {
                const pre = document.createElement('pre');
                pre.className = 'mb-0';
                pre.style.whiteSpace = 'pre-wrap';
                pre.style.wordBreak = 'break-word';
                pre.textContent = JSON.stringify(value, null, 2);
                target.appendChild(pre);
                return;
            }

            if (value === null || value === undefined) {
                target.textContent = '';
                return;
            }

            if (Array.isArray(value)) {
                if (!value.length) {
                    target.textContent = '[]';
                    return;
                }

                const allObjects = value.every(item => item && typeof item === 'object' && !Array.isArray(item));
                if (allObjects) {
                    const innerTable = document.createElement('table');
                    innerTable.className = 'table table-sm table-bordered mb-0';
                    innerTable.style.fontSize = '0.9rem';
                    innerTable.style.marginTop = '0.25rem';

                    const keys = Array.from(value.reduce((acc, item) => {
                        Object.keys(item).forEach(k => acc.add(k));
                        return acc;
                    }, new Set()));

                    const innerHead = document.createElement('thead');
                    const innerHeadRow = document.createElement('tr');
                    keys.forEach(k => {
                        const th = document.createElement('th');
                        th.textContent = k;
                        innerHeadRow.appendChild(th);
                    });
                    innerHead.appendChild(innerHeadRow);
                    innerTable.appendChild(innerHead);

                    const innerBody = document.createElement('tbody');
                    const maxRows = Math.min(value.length, 10);
                    for (let i = 0; i < maxRows; i++) {
                        const row = value[i];
                        const tr = document.createElement('tr');
                        keys.forEach(k => {
                            const td = document.createElement('td');
                            const cellValue = row[k];
                            if (cellValue && typeof cellValue === 'object') {
                                appendStructuredValue(td, cellValue, level + 1);
                            } else {
                                td.textContent = cellValue !== null && cellValue !== undefined ? String(cellValue) : '';
                            }
                            tr.appendChild(td);
                        });
                        innerBody.appendChild(tr);
                    }
                    innerTable.appendChild(innerBody);
                    var innerScroll = document.createElement('div');
                    innerScroll.className = 'ai-chat-table-scroll ai-chat-table-scroll--nested';
                    innerScroll.appendChild(innerTable);
                    target.appendChild(innerScroll);

                    if (value.length > 10) {
                        const more = document.createElement('div');
                        more.className = 'text-muted mt-1';
                        more.style.fontSize = '0.85rem';
                        more.textContent = '+' + String(value.length - 10) + ' more rows';
                        target.appendChild(more);
                    }
                    return;
                }

                const list = document.createElement('ol');
                list.className = 'mb-0 ps-3';
                const maxItems = Math.min(value.length, 10);
                for (let i = 0; i < maxItems; i++) {
                    const li = document.createElement('li');
                    const item = value[i];
                    if (item && typeof item === 'object') {
                        appendStructuredValue(li, item, level + 1);
                    } else {
                        li.textContent = item !== null && item !== undefined ? String(item) : '';
                    }
                    list.appendChild(li);
                }
                target.appendChild(list);
                if (value.length > 10) {
                    const more = document.createElement('div');
                    more.className = 'text-muted mt-1';
                    more.style.fontSize = '0.85rem';
                    more.textContent = '+' + String(value.length - 10) + ' more items';
                    target.appendChild(more);
                }
                return;
            }

            if (typeof value === 'object') {
                const innerTable = document.createElement('table');
                innerTable.className = 'table table-sm table-bordered mb-0';
                innerTable.style.fontSize = '0.9rem';
                const innerBody = document.createElement('tbody');
                Object.keys(value).forEach(key => {
                    const tr = document.createElement('tr');
                    const k = document.createElement('th');
                    k.textContent = key;
                    k.style.whiteSpace = 'nowrap';
                    const v = document.createElement('td');
                    const cellValue = value[key];
                    if (cellValue && typeof cellValue === 'object') {
                        appendStructuredValue(v, cellValue, level + 1);
                    } else {
                        v.textContent = cellValue !== null && cellValue !== undefined ? String(cellValue) : '';
                    }
                    tr.appendChild(k);
                    tr.appendChild(v);
                    innerBody.appendChild(tr);
                });
                innerTable.appendChild(innerBody);
                var objScroll = document.createElement('div');
                objScroll.className = 'ai-chat-table-scroll ai-chat-table-scroll--nested';
                objScroll.appendChild(innerTable);
                target.appendChild(objScroll);
                return;
            }

            target.textContent = String(value);
        }

        // Build table inside message
        const table = document.createElement('table');
        table.className = 'table table-hover align-middle mb-0 sales-data-table';

        // Table header row
        const thead = document.createElement('thead');
        const headerRow = document.createElement('tr');
        tableData.headers.forEach(header => {
            const th = document.createElement('th');
            th.textContent = translateAiHeader(header);
            headerRow.appendChild(th);
        });
        thead.appendChild(headerRow);
        table.appendChild(thead);

        // Table body
        const tbody = document.createElement('tbody');
        tableData.rows.forEach(row => {
            const tr = document.createElement('tr');
            row.forEach(cell => {
                const td = document.createElement('td');
                const parsedCell = tryParseJsonCell(cell);
                appendStructuredValue(td, parsedCell, 0);
                tr.appendChild(td);
            });
            tbody.appendChild(tr);
        });
        table.appendChild(tbody);

        const tableScroll = document.createElement('div');
        tableScroll.className = 'ai-chat-table-scroll';
        tableScroll.appendChild(table);
        container.appendChild(tableScroll);
        scrollToBottom();
    }

    function clearResults() {
        clearChat();

        // Drop ?continue= from URL
        if (typeof history !== 'undefined' && history.replaceState) {
            var url = window.location.pathname + window.location.search.replace(/\?continue=\d+&?|&?continue=\d+/g, '').replace(/\?$/, '');
            history.replaceState({}, '', url || window.location.pathname);
        }

        // Clear input
        if (analysisQuestion) {
            analysisQuestion.value = '';
            analysisQuestion.style.height = 'auto';
            analysisQuestion.focus();
        }
    }

    // Analyze button
    if (analyzeBtn) {
        analyzeBtn.addEventListener('click', function (e) {
            e.preventDefault();
            const question = analysisQuestion ? analysisQuestion.value.trim() : '';

            if (!question) {
                alert(aiT('emptyQuestion', 'Please enter a question for analysis'));
                if (analysisQuestion) {
                    analysisQuestion.focus();
                }
                return;
            }

            if (analyzeBtn.disabled) return; // prevent double submit
            sendAnalysisRequest(question, true);
        });
    }

    // Clear button
    if (clearBtn) {
        clearBtn.addEventListener('click', function () {
            clearResults();
        });
    }

    // Enter in textarea
    if (analysisQuestion) {
        // Auto-grow textarea
        analysisQuestion.addEventListener('input', function () {
            this.style.height = 'auto';
            this.style.height = Math.min(this.scrollHeight, 200) + 'px';
        });

        analysisQuestion.addEventListener('keydown', function (e) {
            if (e.key === 'Enter' && !e.shiftKey && !e.ctrlKey && !e.metaKey) {
                e.preventDefault();
                if (analyzeBtn && !analyzeBtn.disabled && this.value.trim()) {
                    analyzeBtn.click();
                }
            }
        });

        // Focus input on load
        setTimeout(function () {
            if (analysisQuestion) analysisQuestion.focus();
        }, 500);

        // Mobile: padding above keyboard (Visual Viewport API)
        if (searchSection && window.visualViewport && window.matchMedia('(max-width: 768px)').matches) {
            var cardBody = searchSection.closest('.ai-chat-card-body');
            var gapAboveKeyboard = 24;
            var resizeHandler = function () {
                if (!cardBody) return;
                var keyboardHeight = window.innerHeight - window.visualViewport.height;
                if (keyboardHeight > 60 && document.activeElement === analysisQuestion) {
                    cardBody.style.paddingBottom = (keyboardHeight + gapAboveKeyboard) + 'px';
                    // Scroll so input stays above keyboard
                    requestAnimationFrame(function () {
                        var rect = searchSection.getBoundingClientRect();
                        var visibleBottom = window.visualViewport.height - gapAboveKeyboard;
                        if (rect.bottom > visibleBottom) {
                            window.scrollBy(0, rect.bottom - visibleBottom);
                        }
                    });
                } else {
                    cardBody.style.paddingBottom = '';
                }
            };
            window.visualViewport.addEventListener('resize', resizeHandler);
            window.visualViewport.addEventListener('scroll', resizeHandler);
            analysisQuestion.addEventListener('focus', function () {
                setTimeout(function () {
                    resizeHandler();
                    searchSection.scrollIntoView({ behavior: 'smooth', block: 'end', inline: 'nearest' });
                    // Second pass after keyboard (device-dependent delay)
                    setTimeout(function () {
                        if (document.activeElement === analysisQuestion) resizeHandler();
                    }, 450);
                }, 400);
            });
            analysisQuestion.addEventListener('blur', function () {
                if (cardBody) cardBody.style.paddingBottom = '';
            });
        }
    }

    // Resume from history: load thread via ?continue=entry_id
    if (chatMessages) {
        var urlParams = new URLSearchParams(window.location.search);
        var continueId = urlParams.get('continue');
        if (continueId) {
            var id = parseInt(continueId, 10);
            if (!isNaN(id)) {
                setTimeout(function () { loadHistoryEntryAndContinue(id); }, 300);
            }
        }
    }
});
