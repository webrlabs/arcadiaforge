import os
import json
from pathlib import Path
from typing import List, Dict, Any, Optional
from fastapi import APIRouter, HTTPException, Body
from pydantic import BaseModel
import aiosqlite

router = APIRouter()

GENERATIONS_DIR = Path("generations")

class Project(BaseModel):
    id: str
    name: str
    path: str
    has_db: bool

class CreateProjectRequest(BaseModel):
    name: str
    app_spec: str

class UpdateFeatureRequest(BaseModel):
    description: Optional[str] = None
    steps: Optional[List[str]] = None
    priority: Optional[int] = None

class UpdateSpecRequest(BaseModel):
    content: str

@router.get("/projects", response_model=List[Project])
async def list_projects():
    """List all available projects in the generations directory."""
    projects = []
    if not GENERATIONS_DIR.exists():
        return []
    
    for entry in GENERATIONS_DIR.iterdir():
        if entry.is_dir():
            has_db = (entry / ".arcadia" / "project.db").exists()
            projects.append(Project(
                id=entry.name,
                name=entry.name.replace("_", " ").title(),
                path=str(entry),
                has_db=has_db
            ))
    return sorted(projects, key=lambda p: p.name)

@router.post("/projects")
async def create_project(req: CreateProjectRequest):
    """Create a new project folder and app_spec.txt."""
    project_slug = req.name.lower().replace(" ", "_")
    project_path = GENERATIONS_DIR / project_slug
    
    if project_path.exists():
        raise HTTPException(status_code=400, detail="Project already exists")
    
    try:
        project_path.mkdir(parents=True)
        (project_path / "app_spec.txt").write_text(req.app_spec)
        return {"id": project_slug, "message": "Project created"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/projects/{project_id}/db/{table}")
async def get_table_data(project_id: str, table: str, limit: int = 100, offset: int = 0):
    """Generic endpoint to read any table from the project's SQLite DB."""
    db_path = GENERATIONS_DIR / project_id / ".arcadia" / "project.db"
    
    if not db_path.exists():
        raise HTTPException(status_code=404, detail="Database not found")
        
    allowed_tables = {
        "features", "sessions", "events", "artifacts", 
        "checkpoints", "decisions", "hypotheses", 
        "hot_memory", "warm_memory", "cold_memory"
    }
    
    if table not in allowed_tables:
        raise HTTPException(status_code=400, detail=f"Invalid table. Allowed: {', '.join(allowed_tables)}")

    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        try:
            # Safe because we validate table name against allowlist
            cursor = await db.execute(f"SELECT * FROM {table} ORDER BY id ASC LIMIT ? OFFSET ?", (limit, offset))
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

@router.patch("/projects/{project_id}/features/{feature_id}")
async def update_feature(project_id: str, feature_id: int, update: UpdateFeatureRequest):
    """Update a specific feature."""
    db_path = GENERATIONS_DIR / project_id / ".arcadia" / "project.db"
    
    if not db_path.exists():
        raise HTTPException(status_code=404, detail="Database not found")

    updates = []
    params = []

    if update.description is not None:
        updates.append("description = ?")
        params.append(update.description)
    
    if update.steps is not None:
        updates.append("steps = ?")
        params.append(json.dumps(update.steps))
        
    if update.priority is not None:
        updates.append("priority = ?")
        params.append(update.priority)
        
    if not updates:
        return {"message": "No changes requested"}

    query = f"UPDATE features SET {', '.join(updates)} WHERE id = ?"
    params.append(feature_id)

    async with aiosqlite.connect(db_path) as db:
        try:
            await db.execute(query, params)
            await db.commit()
            return {"message": "Feature updated successfully"}
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

@router.get("/projects/{project_id}/spec")
async def get_project_spec(project_id: str):
    """Read the app_spec.txt for a project."""
    spec_path = GENERATIONS_DIR / project_id / "app_spec.txt"
    if not spec_path.exists():
        return {"content": ""}
    return {"content": spec_path.read_text()}

@router.post("/projects/{project_id}/spec")
async def update_project_spec(project_id: str, req: UpdateSpecRequest):
    """Update the app_spec.txt for a project."""
    project_dir = GENERATIONS_DIR / project_id
    if not project_dir.exists():
        raise HTTPException(status_code=404, detail="Project not found")
    
    spec_path = project_dir / "app_spec.txt"
    try:
        spec_path.write_text(req.content)
        return {"message": "Spec updated successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
