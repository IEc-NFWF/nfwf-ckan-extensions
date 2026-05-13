/**
 * Collapsible Facet Filters for CKAN Dataset Search
 */
(function () {
  'use strict';

  var STORAGE_KEY = 'ckan_facet_expanded_state';

  /**
   * Get all currently expanded facet names from the DOM
   */
  function getCurrentExpandedNames() {
    var expanded = [];
    var sections = document.querySelectorAll('.facet-collapsible');
    for (var i = 0; i < sections.length; i++) {
      var section = sections[i];
      var body = section.querySelector('.facet-body');
      var toggle = section.querySelector('.facet-toggle');
      if (body && body.style.display !== 'none' && toggle) {
        var facetName = toggle.getAttribute('data-facet-name');
        if (facetName) {
          expanded.push(facetName);
        }
      }
    }
    return expanded;
  }

  /**
   * Save the expanded facet names to sessionStorage
   */
  function saveExpandedState() {
    try {
      sessionStorage.setItem(STORAGE_KEY, JSON.stringify(getCurrentExpandedNames()));
    } catch (e) {}
  }

  /**
   * Expand a facet section
   */
  function expandSection(section) {
    var body = section.querySelector('.facet-body');
    var caret = section.querySelector('.facet-caret');
    if (!body) return;

    body.style.display = 'block';
    section.classList.add('facet-expanded');
    if (caret) {
      caret.classList.remove('fa-caret-right');
      caret.classList.add('fa-caret-down');
    }
  }

  /**
   * Collapse a facet section
   */
  function collapseSection(section) {
    var body = section.querySelector('.facet-body');
    var caret = section.querySelector('.facet-caret');
    if (!body) return;

    body.style.display = 'none';
    section.classList.remove('facet-expanded');
    if (caret) {
      caret.classList.remove('fa-caret-down');
      caret.classList.add('fa-caret-right');
    }
  }

  document.addEventListener('DOMContentLoaded', function () {

    // --- Toggle Expand/Collapse on click ---
    var toggles = document.querySelectorAll('.facet-toggle');

    for (var i = 0; i < toggles.length; i++) {
      toggles[i].addEventListener('click', function (e) {
        e.preventDefault();

        var section = this.closest('.facet-collapsible');
        var body = section.querySelector('.facet-body');

        if (!body) return;

        if (body.style.display === 'none') {
          expandSection(section);

          var searchInput = body.querySelector('.facet-search');
          if (searchInput) {
            searchInput.focus();
          }
        } else {
          collapseSection(section);
        }

        saveExpandedState();
      });
    }

    // --- Save state before navigating via any facet filter link ---
    var facetLinks = document.querySelectorAll('.facet-collapsible .nav-facet a');
    for (var l = 0; l < facetLinks.length; l++) {
      facetLinks[l].addEventListener('click', function () {
        saveExpandedState();
      });
    }

    // --- Intra-Facet Search ---
    var searchInputs = document.querySelectorAll('.facet-search');

    for (var j = 0; j < searchInputs.length; j++) {
      searchInputs[j].addEventListener('input', function () {
        var query = this.value.toLowerCase().trim();
        var section = this.closest('.facet-collapsible');
        var items = section.querySelectorAll('.facet-list-scrollable .nav-item');
        var noResults = section.querySelector('.facet-no-results');
        var visibleCount = 0;

        for (var k = 0; k < items.length; k++) {
          var label = items[k].querySelector('.item-label');
          var text = label ? label.textContent.toLowerCase() : '';

          if (query === '' || text.indexOf(query) !== -1) {
            items[k].style.display = '';
            visibleCount++;
          } else {
            items[k].style.display = 'none';
          }
        }

        if (noResults) {
          noResults.style.display = (visibleCount === 0 && query !== '') ? 'block' : 'none';
        }
      });

      searchInputs[j].addEventListener('keydown', function (e) {
        if (e.key === 'Enter' || e.keyCode === 13) {
          e.preventDefault();
        }
      });
    }

  });
})();
