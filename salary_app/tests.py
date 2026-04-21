from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.urls import reverse
from django.utils import timezone
from unittest.mock import patch, MagicMock
from salary_app.models import CrmUser, SalaryPayment, Employee, ExpenseType, ProductionExpense
import json
import requests
import logging


class ChatGPTStatusTest(TestCase):
    """Tests for ChatGPT / LLM status endpoint."""

    def setUp(self):
        """Test fixture setup."""
        # Quiet logs during tests
        logging.disable(logging.WARNING)

        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123'
        )
        # CrmUser linked to django user
        self.crm_user = CrmUser.objects.create(
            django_user=self.user,
            user_id=1,
            name='Test',
            last_name='User',
            is_admin=True
        )
        self.client = Client()
        self.client.login(username='testuser', password='testpass123')
    
    def tearDown(self):
        """Restore logging after tests."""
        logging.disable(logging.NOTSET)
    
    @patch('salary_app.ai_views.get_llm_service')
    def test_chatgpt_status_ready(self, mock_get_llm_service):
        """LLM reports ready when configured."""
        # Mock LLM service
        mock_llm_service = MagicMock()
        mock_llm_service.api_key = 'test-api-key'
        mock_llm_service.model_type = 'openai'
        mock_llm_service.model_name = 'gpt-4o'
        mock_llm_service._initialized = True
        
        # Mock successful OpenAI completion
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = 'test'
        mock_llm_service.client.chat.completions.create.return_value = mock_response
        
        mock_get_llm_service.return_value = mock_llm_service
        
        response = self.client.get(reverse('ai_check_model_status'))

        # Assertions
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertEqual(data['status'], 'ready')
        self.assertEqual(data['message'], 'ChatGPT готов к работе')
        self.assertEqual(data['model_type'], 'openai')
        self.assertEqual(data['model_name'], 'gpt-4o')
    
    @patch('salary_app.ai_views.get_llm_service')
    def test_chatgpt_status_not_configured(self, mock_get_llm_service):
        """not_configured when API key is missing."""
        # Mock LLM service with no API key
        mock_llm_service = MagicMock()
        mock_llm_service.api_key = ''
        mock_get_llm_service.return_value = mock_llm_service
        
        response = self.client.get(reverse('ai_check_model_status'))

        # Assertions
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertEqual(data['status'], 'not_configured')
        self.assertIn('OPENAI_API_KEY', data['message'])
    
    @patch('salary_app.ai_views.get_llm_service')
    def test_chatgpt_status_invalid_api_key(self, mock_get_llm_service):
        """Error status on invalid API key."""
        # Mock LLM service
        mock_llm_service = MagicMock()
        mock_llm_service.api_key = 'invalid-key'
        mock_llm_service.model_type = 'openai'
        mock_llm_service.model_name = 'gpt-4o'
        mock_llm_service._initialized = True
        
        # Mock OpenAI auth failure
        error = Exception("Invalid API key provided")
        mock_llm_service.client.chat.completions.create.side_effect = error
        
        mock_get_llm_service.return_value = mock_llm_service
        
        response = self.client.get(reverse('ai_check_model_status'))

        # Assertions
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertEqual(data['status'], 'error')
        # Message should mention API key (EN or RU)
        self.assertTrue('api key' in data['message'].lower() or 'ключ' in data['message'].lower())
    
    @patch('salary_app.ai_views.get_llm_service')
    def test_chatgpt_status_rate_limit(self, mock_get_llm_service):
        """Error status on rate limit."""
        # Mock LLM service
        mock_llm_service = MagicMock()
        mock_llm_service.api_key = 'test-api-key'
        mock_llm_service.model_type = 'openai'
        mock_llm_service.model_name = 'gpt-4o'
        mock_llm_service._initialized = True
        
        # Mock rate limit from API
        error = Exception("Rate limit exceeded")
        mock_llm_service.client.chat.completions.create.side_effect = error
        
        mock_get_llm_service.return_value = mock_llm_service
        
        response = self.client.get(reverse('ai_check_model_status'))

        # Assertions
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertEqual(data['status'], 'error')
        self.assertIn('лимит запросов', data['message'])
    
    @patch('salary_app.ai_views.get_llm_service')
    def test_chatgpt_status_connection_error(self, mock_get_llm_service):
        """Error status on connection failure."""
        # Mock LLM service
        mock_llm_service = MagicMock()
        mock_llm_service.api_key = 'test-api-key'
        mock_llm_service.model_type = 'openai'
        mock_llm_service.model_name = 'gpt-4o'
        mock_llm_service._initialized = True
        
        # Mock connection error
        mock_llm_service.client.chat.completions.create.side_effect = requests.exceptions.ConnectionError(
            "Connection failed"
        )
        
        mock_get_llm_service.return_value = mock_llm_service
        
        response = self.client.get(reverse('ai_check_model_status'))

        # Assertions
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertEqual(data['status'], 'error')
        self.assertIn('подключиться', data['message'])
    
    @patch('salary_app.ai_views.get_llm_service')
    def test_chatgpt_status_initialization_failed(self, mock_get_llm_service):
        """Error when LLM client fails to initialize."""
        # Mock LLM service
        mock_llm_service = MagicMock()
        mock_llm_service.api_key = 'test-api-key'
        mock_llm_service.model_type = 'openai'
        mock_llm_service.model_name = 'gpt-4o'
        mock_llm_service._initialized = False
        
        # initialize() returns False
        mock_llm_service.initialize.return_value = False
        
        mock_get_llm_service.return_value = mock_llm_service
        
        response = self.client.get(reverse('ai_check_model_status'))

        # Assertions
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertEqual(data['status'], 'error')
        self.assertIn('инициализировать', data['message'])
    
    def test_chatgpt_status_requires_login(self):
        """Unauthenticated users get redirected to login."""
        self.client.logout()

        response = self.client.get(reverse('ai_check_model_status'))

        self.assertEqual(response.status_code, 302)  # redirect to login
    
    @patch('salary_app.ai_views.get_llm_service')
    def test_chatgpt_status_general_exception(self, mock_get_llm_service):
        """Generic exception surfaces as error status."""
        # Mock LLM service
        mock_llm_service = MagicMock()
        mock_llm_service.api_key = 'test-api-key'
        mock_llm_service.model_type = 'openai'
        mock_llm_service.model_name = 'gpt-4o'
        mock_llm_service._initialized = True
        
        # Unexpected exception from API call
        mock_llm_service.client.chat.completions.create.side_effect = Exception("Unexpected error")
        
        mock_get_llm_service.return_value = mock_llm_service
        
        response = self.client.get(reverse('ai_check_model_status'))

        # Assertions
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertEqual(data['status'], 'error')
        self.assertIn('Ошибка', data['message'])


class TemplateRegressionTest(TestCase):
    """Regression tests that lock behavior after template cleanup."""

    def setUp(self):
        self.user = User.objects.create_user(
            username='adminuser',
            password='testpass123',
        )
        self.crm_user = CrmUser.objects.create(
            django_user=self.user,
            user_id=777,
            name='Admin',
            last_name='User',
            is_admin=True,
        )
        self.client = Client()
        self.client.login(username='adminuser', password='testpass123')

    def test_salary_payment_edit_uses_shared_form_template(self):
        payment = SalaryPayment.objects.create(
            manager=self.crm_user,
            amount='1234.56',
            payment_datetime=timezone.now(),
        )

        response = self.client.get(reverse('salary_payment_edit', kwargs={'pk': payment.pk}))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'salary/salary_payment_form.html')

    def test_modal_placeholders_render_loading_text(self):
        salary_payment = SalaryPayment.objects.create(
            manager=self.crm_user,
            amount='100.00',
            payment_datetime=timezone.now(),
        )
        employee = Employee.objects.create(name='Employee For Test')
        expense_type = ExpenseType.objects.create(name='ExpenseType For Test')
        ProductionExpense.objects.create(
            employee=employee,
            expense_type=expense_type,
            amount='50.00',
            expense_date=timezone.now(),
            comment='test',
        )

        salary_response = self.client.get(reverse('salary_payment_list'))
        self.assertContains(salary_response, 'class="text-center text-muted py-3"')

        expense_response = self.client.get(reverse('production_expense_list'))
        self.assertContains(expense_response, 'class="text-center text-muted py-3"')

        users_response = self.client.get(reverse('users_list'))
        self.assertContains(users_response, 'class="text-center text-muted py-3"')

    def test_ai_history_page_keeps_continue_navigation_flow(self):
        response = self.client.get(reverse('ai_analysis_history'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "window.location.href = AI_ANALYSIS_URL + '?continue=' + entryId;")
        self.assertNotContains(response, 'function showHistoryEntry(')
