document.addEventListener("DOMContentLoaded", function () {
  
  // Инициализация всплывающих подсказок Bootstrap (для комментариев и т.д.)
  var tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
  if (tooltipTriggerList.length > 0) {
      var tooltipList = tooltipTriggerList.map(function (tooltipTriggerEl) {
        return new bootstrap.Tooltip(tooltipTriggerEl);
      });
  }

  const form = document.getElementById('uploadForm');
  const filterMonthRadio = document.getElementById('filter_month');
  const filterDateRangeRadio = document.getElementById('filter_date_range');
  const monthFilterDiv = document.getElementById('month_filter');
  const dateRangeDiv = document.getElementById('date_range_filter');
  const managerSelect = document.getElementById('id_manager');
  const salaryField = document.getElementById('remaining_salary_field');
  const yearFilterDiv = document.getElementById('year_filter');
  const amountInput = document.getElementById("id_amount");


  // Toast уведомления
  window.showToast = function(message, type = "success") {
    const toast = document.getElementById("fixed-toast");
    const toastMessage = document.getElementById("toast-message");

    if (!toast || !toastMessage) {
      console.warn("Элемент тоста не найден");
      return;
    }

    toastMessage.textContent = message;

    toast.classList.remove("bg-success", "bg-danger", "d-none");

    if (type === "error") {
      toast.classList.add("bg-danger");
      toast.classList.remove("bg-success");
    } else {
      toast.classList.add("bg-success");
      toast.classList.remove("bg-danger");
    }

    // Автоматическое скрытие
    if (type !== "loading") {
      setTimeout(() => {
        toast.classList.add("d-none");
      }, 3000);
    }
  }

  

  
  // Переключение фильтров
  function toggleFilters() {
    const isMonth = filterMonthRadio?.checked;
    monthFilterDiv?.classList.toggle('d-none', !isMonth);
    yearFilterDiv?.classList.toggle('d-none', !isMonth);
    dateRangeDiv?.classList.toggle('d-none', isMonth);
  }

  filterMonthRadio?.addEventListener('change', toggleFilters);
  filterDateRangeRadio?.addEventListener('change', toggleFilters);
  toggleFilters();

  function spacedNumber(num) {
    if (num == null) return '';
    const parts = Number(num).toFixed(2).split('.');
    parts[0] = parts[0].replace(/\B(?=(\d{3})+(?!\d))/g, " ");
    return parts.join('.');
  }


  // Остаток зарплаты
  managerSelect?.addEventListener('change', function () {
    const managerId = this.value;
    if (!managerId) {
      salaryField.value = '';
      return;
    }

    fetch(`/get-remaining-salary/?manager_id=${managerId}`)
      .then(response => response.json())
      .then(data => {
        salaryField.value = spacedNumber(data.remaining_salary);
      })
      .catch(error => {
        console.error("Ошибка при запросе остатка зарплаты:", error);
      });
  });


 if (amountInput) {
    amountInput.addEventListener("input", function (e) {
      let input = e.target;
      let cursorPos = input.selectionStart;

      // Убираем пробелы
      let rawValue = input.value.replace(/\s+/g, '');

      // Считаем пробелы ДО форматирования
      let spacesBefore = (input.value.slice(0, cursorPos).match(/\s/g) || []).length;

      // Разделяем на целую и дробную части
      let [integerPart, decimalPart] = rawValue.split('.');
      integerPart = integerPart.replace(/\B(?=(\d{3})+(?!\d))/g, ' ');

      let formattedValue = decimalPart !== undefined
        ? `${integerPart}.${decimalPart}`
        : integerPart;

      input.value = formattedValue;

      // Считаем пробелы ПОСЛЕ форматирования
      let spacesAfter = (formattedValue.slice(0, cursorPos).match(/\s/g) || []).length;

      // Восстанавливаем позицию курсора
      input.selectionStart = input.selectionEnd = cursorPos + (spacesAfter - spacesBefore);
    });

    amountInput.addEventListener("blur", function (e) {
      let value = e.target.value.replace(/\s+/g, '');
      if (value && !value.includes('.')) {
        e.target.value = e.target.value + '.00';
      }
    });
  }

  $(document).on('input', '#expenseModal input[name="amount"]', function() {
    // Remove normal spaces and non-breaking spaces for parsing
    var raw = $(this).val().replace(/[\s\u00A0\u202F]+/g, '');
    // Allow digits and optional decimal separator
    raw = raw.replace(',', '.');
    if (/^\d*(?:\.\d*)?$/.test(raw) && raw.length > 0) {
        var parts = raw.split('.');
        var integerPart = parts[0] || '0';
        var decimalPart = parts[1] !== undefined ? parts[1] : undefined;
        // Insert spaces as thousand separators manually to have consistent behavior
        integerPart = integerPart.replace(/\B(?=(\d{3})+(?!\d))/g, ' ');
        var formatted = decimalPart !== undefined ? integerPart + '.' + decimalPart : integerPart;
        $(this).val(formatted);
    }
  });

  // On submit, strip all spaces and NBSP from amount to avoid server-side validation errors
  $(document).on('submit', '#expenseModal form', function() {
    var $amount = $('#expenseModal input[name="amount"]');
    if ($amount.length) {
      var cleaned = $amount.val().replace(/[\s\u00A0\u202F]+/g, '').replace(',', '.');
      $amount.val(cleaned);
    }
  });


  // Тоггл строк продаж
  document.querySelectorAll(".toggle-btn").forEach(button => {
    const monthKey = button.getAttribute("data-month");
    
    // Оберните селектор в обратные кавычки (`), чтобы он стал валидной строкой
    const detailRows = document.querySelectorAll(`.month-details.month-${monthKey}`);

    if (detailRows.length === 0) return;

    button.addEventListener("click", () => {
      const isHidden = detailRows[0].classList.contains("d-none");

      detailRows.forEach(row => {
        row.classList.toggle("d-none");
      });
      
      button.textContent = isHidden ? "Свернуть" : "Развернуть";
    });
  });

  
   
  // Печать выплат ЗП (со страницы "Отчет по зарплате")
  document.querySelectorAll(".print-btn").forEach(button => {
    button.addEventListener("click", function() {
      // Get data from button attributes
      const manager = this.dataset.manager;
      const date = this.dataset.date;
      const amount = this.dataset.amount;

      // Populate the hidden print area
      const printManagerEl = document.getElementById('printSalaryManager');
      const printDateEl = document.getElementById('printSalaryDate');
      const printAmountEl = document.getElementById('printSalaryAmount');

      if (!printManagerEl || !printDateEl || !printAmountEl) {
          console.error('Один или несколько элементов для печати ЗП не найдены на странице.');
          return;
      }

      printManagerEl.textContent = manager;
      printDateEl.textContent = date;
      printAmountEl.innerHTML = amount; // amount from data-attribute already contains '₽'

      // Open a new window, write the content, and print it
      const printArea = document.getElementById('printSalaryPaymentArea');
      if (!printArea) {
          console.error('Контейнер для печати ЗП не найден.');
          return;
      }
      const printContent = printArea.innerHTML;
      const printWindow = window.open('', '_blank');
      printWindow.document.write('<html><head><title>Печать выплаты</title></head><body>' + printContent + '</body></html>');
      printWindow.document.close();
      
      setTimeout(() => { printWindow.print(); printWindow.close(); }, 250);
    });
  });

  // Печать производственных расходов (со страницы "Производство")
  const expensePrintButtons = document.querySelectorAll('.print-expense-btn');
  if (expensePrintButtons.length > 0) {
    expensePrintButtons.forEach(button => {
      button.addEventListener('click', function() {
        // Get data from button attributes
        const employee = this.dataset.employee;
        const expenseType = this.dataset.expenseType;
        const date = this.dataset.date;
        const amount = this.dataset.amount;
        const comment = this.dataset.comment;

        // Populate the hidden print area
        const printEmployeeEl = document.getElementById('printExpenseEmployee');
        const printTypeEl = document.getElementById('printExpenseType');
        const printDateEl = document.getElementById('printExpenseDate');
        const printAmountEl = document.getElementById('printExpenseAmount');
        const commentRow = document.getElementById('printExpenseCommentRow');
        const commentEl = document.getElementById('printExpenseComment');

        if (!printEmployeeEl || !printTypeEl || !printDateEl || !printAmountEl || !commentRow || !commentEl) {
            console.error('Один или несколько элементов для печати не найдены на странице.');
            return;
        }

        printEmployeeEl.textContent = employee;
        printTypeEl.textContent = expenseType;
        printDateEl.textContent = date;
        printAmountEl.innerHTML = amount + ' ₽';
        
        if (comment && comment.trim() !== '') {
          commentEl.innerHTML = comment;
          commentRow.style.display = 'flex';
        } else {
          commentRow.style.display = 'none';
        }

        const printArea = document.getElementById('printExpenseArea');
        const printContent = printArea.innerHTML;
        const printWindow = window.open('', '_blank');
        printWindow.document.write('<html><head><title>Печать расхода</title></head><body>' + printContent + '</body></html>');
        printWindow.document.close();
        
        setTimeout(() => { printWindow.print(); printWindow.close(); }, 250);
      });
    });
  }

  // Обновление с тостом и перезагрузкой
  const formUpdate = document.getElementById("updateSalesForm");

  if (formUpdate) {
    let isSubmitting = false;

    formUpdate.addEventListener("submit", function (e) {
      e.preventDefault();

      if (isSubmitting) return; // ⛔ Предотвращаем повторный запуск
      isSubmitting = true;

      if (!confirm("Загрузить новые сделки из Bitrix24?")) {
        isSubmitting = false;
        return;
      }

      const toast = document.getElementById("fixed-toast");
      const button = formUpdate.querySelector("button[type=submit]");

      // 🔒 Блокируем кнопку
      if (button) button.disabled = true;

      if (toast) {
        toast.classList.remove("d-none");
        toast.classList.remove("bg-danger");
      }

      fetch(formUpdate.action, {
        method: "POST",
        headers: {
          "X-CSRFToken": document.querySelector("[name=csrfmiddlewaretoken]").value,
          "Accept": "application/json",
        },
      })
        .then((response) => {
          if (!response.ok) {
            return response.text().then((text) => {
              const errorMessage = "Ошибка сети: " + text;
              showToast(errorMessage, "error");
              throw new Error(errorMessage);
            });
          }
          const contentType = response.headers.get("content-type") || "";
          if (!contentType.includes("application/json")) {
            return response.text().then((text) => {
              throw new Error("Ожидался JSON, но получен другой контент:\n" + text);
            });
          }
          return response.json();
        })
        .then((data) => {
          if (data.success) {
            showToast(data.message || "Данные успешно загружены!");
            setTimeout(() => location.reload(), 1000);
          } else {
            throw new Error(data.error || "Неизвестная ошибка");
          }
        })
        .catch((err) => {
          console.error("Ошибка:", err);
          showToast("Ошибка загрузки данных", "error");
        })
        .finally(() => {
          isSubmitting = false;
          if (button) button.disabled = false; // 🔓 Разблокируем кнопку
        });
    });
  }
});
$(document).ready(function() {
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
    $('.table-month-summary').on('click', function() {
        const row = $(this);
        const button = row.find('.toggle-btn');
        
        // Toggle the details row
        row.next('.month-details-wrapper').toggleClass('d-none');
        
        // Toggle the chevron icon and the row's expanded state
        button.toggleClass('expanded');
        row.toggleClass('expanded-row');
    });

    // --- In-memory Table Sorting ---
    $('.card').on('click', '.sortable-header', function() {
        const header = $(this);
        const table = header.closest('table');
        const tbody = table.find('tbody');
        const rows = tbody.find('tr').toArray();
        const sortKeyIndex = header.data('sort-key');
        const sortType = header.data('sort-type');
        
        let currentOrder = header.data('sort-order') || 'desc';
        let newOrder = currentOrder === 'asc' ? 'desc' : 'asc';
        
        // Reset other headers
        table.find('.sortable-header').not(header).each(function() {
            $(this).removeData('sort-order');
            $(this).removeClass('asc desc');
            $(this).find('.sort-icon').html('');
        });

        header.data('sort-order', newOrder);
        header.removeClass('asc desc').addClass(newOrder);
        
        const ascIcon = '<i class="bi bi-caret-up-fill"></i>';
        const descIcon = '<i class="bi bi-caret-down-fill"></i>';
        header.find('.sort-icon').html(newOrder === 'asc' ? ascIcon : descIcon);


        rows.sort(function(a, b) {
            const aVal = $(a).find('td').eq(sortKeyIndex).text().trim();
            const bVal = $(b).find('td').eq(sortKeyIndex).text().trim();

            let comparison = 0;
            if (sortType === 'number') {
                // Remove spaces, currency symbols, and convert comma to dot
                const aNum = parseFloat(aVal.replace(/\s/g, '').replace(/₽/g, '').replace(',', '.').replace(/[^\d.-]/g, '')) || 0;
                const bNum = parseFloat(bVal.replace(/\s/g, '').replace(/₽/g, '').replace(',', '.').replace(/[^\d.-]/g, '')) || 0;
                comparison = aNum - bNum;
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
    // Цветовая палитра из SCSS дизайна
    // Фиолетовый для Продаж
    const primaryAccent = 'rgba(108, 99, 255, 0.9)';   // #6c63ff - для Продаж
    const primaryAccentBorder = 'rgba(108, 99, 255, 1)';
    
    // Жёлтый для Выплат
    const salaryColor = 'rgba(255, 212, 59, 0.9)';  // #ffd43b - для Выплат
    const salaryColorBorder = 'rgba(255, 212, 59, 1)';
    
    // Оранжевый для Расходов
    const expensesColor = 'rgba(255, 106, 51, 0.9)';  // #ff6a33 - для Расходов
    const expensesColorBorder = 'rgba(255, 106, 51, 1)';
    
    // Зелёный для Прибыли
    const profitColor = 'rgba(76, 217, 100, 0.9)';  // #4cd964 - для Прибыли
    const profitColorBorder = 'rgba(76, 217, 100, 1)';
    
    // Получаем цвета из CSS переменных для текущей темы
    const root = document.documentElement;
    const chartGridColor = getComputedStyle(root).getPropertyValue('--chart-grid-color').trim() || 'rgba(228, 231, 238, 0.5)';
    const gridColor = chartGridColor;  // Используем CSS переменную для цвета сетки
    const chartTextColor = getComputedStyle(root).getPropertyValue('--chart-text-color').trim() || '#2E2E3A';
    const chartAxisColor = getComputedStyle(root).getPropertyValue('--chart-axis-color').trim() || '#6F7381';
    
    // Последовательная палитра для множественных категорий (из SCSS дизайна)
    const sequentialPalette = [
        'rgba(108, 99, 255, 0.9)',   // #6c63ff - фиолетовый (продажи)
        'rgba(255, 212, 59, 0.9)',   // #ffd43b - жёлтый (выплаты)
        'rgba(255, 106, 51, 0.9)',   // #ff6a33 - оранжевый (расходы)
        'rgba(76, 217, 100, 0.9)',   // #4cd964 - зелёный (прибыль)
        'rgba(156, 39, 176, 0.9)',   // #9C27B0 - пурпурный
        'rgba(186, 104, 200, 0.9)',  // #BA68C8 - светлый пурпурный
        'rgba(255, 183, 77, 0.9)',   // #FFB74D - светлый оранжевый
        'rgba(129, 199, 132, 0.9)',  // #81C784 - светлый зелёный
        'rgba(255, 152, 0, 0.9)',    // #FF9800 - оранжевый
        'rgba(76, 175, 80, 0.9)'     // #4CAF50 - зелёный
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
    
    // Улучшенные настройки графиков с современным дизайном
    const chartOptions = {
        responsive: true,
        maintainAspectRatio: false,
        interaction: {
            intersect: false,
            mode: 'index'
        },
        animation: {
            duration: 800, // Длительность анимации при загрузке
            easing: 'easeOutQuart' // Плавная анимация
        },
        scales: { 
            y: { 
                beginAtZero: true,
                grid: {
                    color: gridColor, // Используется из переменной gridColor
                    lineWidth: 1,
                    drawBorder: false
                },
                ticks: {
                    color: chartAxisColor, // Используем CSS переменную для цвета текста осей
                    font: {
                        size: 12 // 12px для осей графика
                    }
                }
            },
            x: {
                grid: {
                    display: false
                },
                ticks: {
                    color: chartAxisColor, // Используем CSS переменную для цвета текста осей
                    font: {
                        size: 12 // 12px для осей графика
                    }
                }
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
                        size: 12 // 12px для легенды графика
                    },
                    color: chartTextColor // Используем CSS переменную для цвета текста легенды
                },
                onClick: function(e, legendItem) {
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
                    size: 14, // 14px для заголовка tooltip
                    weight: '600' // SemiBold
                },
                bodyFont: {
                    size: 12 // 12px для текста tooltip
                },
                borderColor: 'rgba(255, 255, 255, 0.1)',
                borderWidth: 1,
                cornerRadius: 8,
                displayColors: true,
                callbacks: {
                    label: function(context) {
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
                            label += formatted + ' ₽';
                        }
                        return label;
                    }
                }
            }
        }
    };
    
    // Опции для графиков по менеджерам - показываем только конкретный столбец при наведении
    const managerChartOptions = {
        ...chartOptions,
        interaction: {
            intersect: false,
            mode: 'point' // Показываем только конкретный столбец, а не все менеджеры за месяц
        }
    };
    
    try {
        Chart.register(ChartDataLabels);

        // Legacy palette for backward compatibility (will be replaced with sequential)
        const palette = sequentialPalette;

        // Chart 1: Sales & Salary - Purple for Sales, Mint for Salary
        const chartDataEl = document.getElementById('chart-data');
        if (chartDataEl) {
            const chartData = JSON.parse(chartDataEl.textContent);
            const ctx = document.getElementById('salesSalaryChart').getContext('2d');
            window.salesChart = new Chart(ctx, {
                type: 'bar',
                data: {
                    labels: chartData.labels,
                    datasets: [{
                        label: 'Продажи',
                        data: chartData.sales,
                        backgroundColor: primaryAccent, // #6c63ff - Фиолетовый
                        borderColor: primaryAccentBorder,
                        borderWidth: 1.5,
                        borderRadius: 6 // Закругление углов баров
                    }, { 
                        label: 'Зарплата',
                        data: chartData.salaries,
                        backgroundColor: salaryColor, // #ffd43b - Жёлтый
                        borderColor: salaryColorBorder,
                        borderWidth: 1.5,
                        borderRadius: 6 // Закругление углов баров
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
                dataset.borderRadius = 6; // Закругление углов баров
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
                options: {
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
                                pointBorderWidth: 0, // Убираем белые границы в точках легенды
                                font: {
                                    size: 12
                                },
                                color: chartTextColor // Используем CSS переменную для цвета текста легенды
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
                                label: function(context) {
                                    const label = context.label || '';
                                    const value = context.parsed;
                                    const total = context.dataset.data.reduce((a, b) => a + b, 0);
                                    const percentage = ((value / total) * 100).toFixed(1);
                                    const formatted = value.toLocaleString('ru-RU', {
                                        minimumFractionDigits: 0,
                                        maximumFractionDigits: 0
                                    });
                                    return label + ': ' + formatted + ' ₽ (' + percentage + '%)';
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
                            color: '#fff',
                            font: {
                                weight: 'bold',
                                size: 11
                            }
                        }
                    }
                }
            });

            $('input[name="manager_chart_type"]').on('change', function() {
                if ($(this).val() === 'bar') {
                    $('#managerPieChartContainer').addClass('d-none');
                    $('#managerBarChartContainer').removeClass('d-none');
                } else {
                    $('#managerBarChartContainer').addClass('d-none');
                    $('#managerPieChartContainer').removeClass('d-none');
                    managerSalesPieChart.resize();
                }
                // Обновляем классы active на labels
                $('input[name="manager_chart_type"]').each(function() {
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
            window.expenseMonthChart = new Chart(expenseCtx, {
                type: 'bar',
                data: {
                    labels: expenseChartData.labels,
                    datasets: [{
                        label: 'Расходы',
                        data: expenseChartData.data,
                        backgroundColor: expensesColor, // #ff6a33 - Оранжевый
                        borderColor: expensesColorBorder,
                        borderWidth: 1.5,
                        borderRadius: 6 // Закругление углов баров
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
                dataset.borderRadius = 6; // Закругление углов баров
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
                options: {
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
                                pointBorderWidth: 0, // Убираем белые границы в точках легенды
                                font: {
                                    size: 12
                                },
                                color: chartTextColor // Используем CSS переменную для цвета текста легенды
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
                                label: function(context) {
                                    const label = context.label || '';
                                    const value = context.parsed;
                                    const total = context.dataset.data.reduce((a, b) => a + b, 0);
                                    const percentage = ((value / total) * 100).toFixed(1);
                                    const formatted = value.toLocaleString('ru-RU', {
                                        minimumFractionDigits: 0,
                                        maximumFractionDigits: 0
                                    });
                                    return label + ': ' + formatted + ' ₽ (' + percentage + '%)';
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
                            color: '#fff',
                            font: {
                                weight: 'bold',
                                size: 11
                            }
                        }
                    }
                }
            });

            $('input[name="expense_type_chart_type"]').on('change', function() {
                if ($(this).val() === 'bar') {
                    $('#expenseTypePieChartContainer').addClass('d-none');
                    $('#expenseTypeBarChartContainer').removeClass('d-none');
                } else {
                    $('#expenseTypeBarChartContainer').addClass('d-none');
                    $('#expenseTypePieChartContainer').removeClass('d-none');
                    expenseTypePieChart.resize();
                }
                // Обновляем классы active на labels
                $('input[name="expense_type_chart_type"]').each(function() {
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
                dataset.borderRadius = 6; // Закругление углов баров
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
                options: {
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
                                pointBorderWidth: 0, // Убираем белые границы в точках легенды
                                font: {
                                    size: 12
                                },
                                color: chartTextColor // Используем CSS переменную для цвета текста легенды
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
                                label: function(context) {
                                    const label = context.label || '';
                                    const value = context.parsed;
                                    const total = context.dataset.data.reduce((a, b) => a + b, 0);
                                    const percentage = ((value / total) * 100).toFixed(1);
                                    const formatted = value.toLocaleString('ru-RU', {
                                        minimumFractionDigits: 0,
                                        maximumFractionDigits: 0
                                    });
                                    return label + ': ' + formatted + ' ₽ (' + percentage + '%)';
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
                            color: '#fff',
                            font: {
                                weight: 'bold',
                                size: 11
                            }
                        }
                    }
                }
            });

            $('input[name="salary_chart_type"]').on('change', function() {
                if ($(this).val() === 'bar') {
                    $('#salaryPieChartContainer').addClass('d-none');
                    $('#salaryBarChartContainer').removeClass('d-none');
                } else {
                    $('#salaryBarChartContainer').addClass('d-none');
                    $('#salaryPieChartContainer').removeClass('d-none');
                    salaryManagerPieChart.resize();
                }
                // Обновляем классы active на labels
                $('input[name="salary_chart_type"]').each(function() {
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

    $('button[data-bs-toggle="pill"]').on('shown.bs.tab', function (e) {
        // Resize all charts when window is resized
        const resizeCharts = () => {
            const charts = [
                window.salesChart,
                window.managerChart,
                window.managerSalesPieChart,
                window.expenseMonthChart,
                window.expenseTypeChart,
                window.expenseTypePieChart,
                window.salaryManagerMonthChart,
                window.salaryManagerPieChart
            ];
            
            charts.forEach(chart => {
                if (chart) {
                    chart.resize();
                }
            });
        };
        
        // Add resize event listener with debounce
        let resizeTimeout;
        window.addEventListener('resize', () => {
            clearTimeout(resizeTimeout);
            resizeTimeout = setTimeout(() => {
                resizeCharts();
            }, 100);
        });
        
        // Also resize when switching tabs
        $('button[data-bs-toggle="pill"]').on('shown.bs.tab', function() {
            setTimeout(resizeCharts, 100);
        });
        
        if (window.salesChart) {
            window.salesChart.resize();
        }
        if (window.managerChart) {
            window.managerChart.resize();
        }
        if (window.expenseMonthChart) {
            window.expenseMonthChart.resize();
        }
        if (window.expenseTypeChart) {
            window.expenseTypeChart.resize();
        }
        if (window.salaryManagerMonthChart) {
            window.salaryManagerMonthChart.resize();
        }
    });

    $(window).on('load', function() {
        window.dispatchEvent(new Event('resize'));
    });

    // Функция для обновления всех графиков при смене темы
    function updateChartsTheme() {
        // Получаем новые цвета из CSS переменных для текущей темы
        const root = document.documentElement;
        const chartGridColor = getComputedStyle(root).getPropertyValue('--chart-grid-color').trim() || 'rgba(228, 231, 238, 0.5)';
        const chartTextColor = getComputedStyle(root).getPropertyValue('--chart-text-color').trim() || '#2E2E3A';
        const chartAxisColor = getComputedStyle(root).getPropertyValue('--chart-axis-color').trim() || '#6F7381';

        // Обновляем все графики с новыми цветами
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
            if (chart && typeof chart.update === 'function') {
                // Обновляем цвета осей
                if (chart.options && chart.options.scales) {
                    if (chart.options.scales.y) {
                        if (chart.options.scales.y.grid) {
                            chart.options.scales.y.grid.color = chartGridColor;
                        }
                        if (chart.options.scales.y.ticks) {
                            chart.options.scales.y.ticks.color = chartAxisColor;
                        }
                    }
                    if (chart.options.scales.x) {
                        if (chart.options.scales.x.ticks) {
                            chart.options.scales.x.ticks.color = chartAxisColor;
                        }
                    }
                }

                // Обновляем цвет легенды
                if (chart.options && chart.options.plugins && chart.options.plugins.legend) {
                    if (chart.options.plugins.legend.labels) {
                        chart.options.plugins.legend.labels.color = chartTextColor;
                    }
                }

                // Обновляем график
                chart.update('none'); // 'none' отключает анимацию для быстрого обновления
                
                // Для круговых диаграмм принудительно обновляем легенду
                if (chart.config && chart.config.type === 'pie') {
                    chart.update('none');
                }
            }
        });
    }

    // Экспортируем функцию для использования в theme-toggle.js
    window.updateChartsTheme = updateChartsTheme;
});