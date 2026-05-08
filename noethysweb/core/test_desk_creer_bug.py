# -*- coding: utf-8 -*-
# Test pour mettre en évidence le bug de permission desk_creer

from django.test import TestCase, override_settings
from core.utils.utils_permissions import GetPermissionsPossibles


class TestDeskCreerBug(TestCase):
    """Test qui met en évidence le problème de migration de permission desk_creer"""

    def test_desk_creer_permission_missing_without_secret_export_desk(self):
        """
        Ce test met en évidence le bug :
        Quand SECRET_EXPORT_DESK=None, la permission desk_creer n'est pas générée,
        ce qui cause sa suppression lors des migrations.
        """
        with override_settings(SECRET_EXPORT_DESK=None):
            permissions = GetPermissionsPossibles()
            desk_creer_permissions = [perm for perm in permissions 
                                   if perm[0] == 'desk_creer']
            
            # Ce test va échouer, démontrant le problème
            self.assertEqual(len(desk_creer_permissions), 1,
                           "PROBLÈME DÉTECTÉ: La permission 'desk_creer' n'est pas "
                           "générée quand SECRET_EXPORT_DESK=None. "
                           "Cela explique pourquoi elle est supprimée lors des migrations.")

    def test_desk_creer_permission_present_with_secret_export_desk(self):
        """
        Test normal : avec SECRET_EXPORT_DESK défini, la permission devrait être présente.
        """
        with override_settings(SECRET_EXPORT_DESK="test_value"):
            permissions = GetPermissionsPossibles()
            desk_creer_permissions = [perm for perm in permissions 
                                   if perm[0] == 'desk_creer']
            
            self.assertEqual(len(desk_creer_permissions), 1,
                           "La permission 'desk_creer' devrait être présente "
                           "quand SECRET_EXPORT_DESK est défini.")
