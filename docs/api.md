# API reference

This page documents the public modules, grouped by the stage of the loop they
serve. The everyday names, such as `import_org`, `import_csv`, `render_week`,
and `dashboard_html`, are shown below under the module that owns them.

## Database and models

```{eval-rst}
.. automodule:: writing_habit.db
   :members:

.. automodule:: writing_habit.models
   :members:
```

## Plan

```{eval-rst}
.. automodule:: writing_habit.plan_import
   :members:
```

## Track

```{eval-rst}
.. automodule:: writing_habit.track.csv_actuals
   :members:

.. automodule:: writing_habit.track.ics_actuals
   :members:

.. automodule:: writing_habit.track.manual
   :members:
```

## Compare

```{eval-rst}
.. automodule:: writing_habit.compare.queries
   :members:

.. automodule:: writing_habit.compare.report
   :members:
```

## Dashboard

```{eval-rst}
.. automodule:: writing_habit.dashboard
   :members:
```

## Schedule codes

```{eval-rst}
.. automodule:: writing_habit.name
   :members:
```

## Command line

```{eval-rst}
.. automodule:: writing_habit.cli
   :members:
```
